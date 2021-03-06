"""
Copyright (c) 2018 iCyP
Released under the MIT license
https://opensource.org/licenses/mit-license.php

"""

# codig :utf-8
#for python3.5 - for blender2.79
from .binaly_loader import Binaly_Reader
from ..gl_const import GL_CONSTANS as GLC
from .. import V_Types as VRM_Types
from ..V_Types import nested_json_value_getter as json_get
from . import vrm2pydata_factory
import os,re,copy
from math import sqrt,pow
import json
import numpy
from collections import OrderedDict




def parse_glb(data: bytes):
    reader = Binaly_Reader(data)
    magic = reader.read_str(4)
    if magic != 'glTF':
        raise Exception('magic not found: #{}'.format(magic))

    version = reader.read_as_dataType(GLC.UNSIGNED_INT)
    if version != 2:
        raise Exception('version:#{} is not 2'.format(version))

    size = reader.read_as_dataType(GLC.UNSIGNED_INT)
    size -= 12

    json_str = None
    body = None
    while size > 0:
        # print(size)

        if json_str is not None and body is not None:
            raise Exception('this vrm has chunks, this importer reads one chunk only.')

        chunk_size = reader.read_as_dataType(GLC.UNSIGNED_INT)
        size -= 4

        chunk_type = reader.read_str(4)
        size -= 4

        chunk_data = reader.read_binaly(chunk_size)
        size -= chunk_size

        if chunk_type == 'BIN\x00':
            body = chunk_data
        elif chunk_type == 'JSON':
            json_str = chunk_data.decode('utf-8')#blenderのpythonverが古く自前decode要す
        else:
            raise Exception('unknown chunk_type: {}'.format(chunk_type))

    return json.loads(json_str,object_pairs_hook=OrderedDict), body

#あくまでvrm(の特にバイナリ)をpythonデータ化するだけで、blender型に変形はここではしない
def read_vrm(model_path):
    vrm_pydata = VRM_Types.VRM_pydata(filepath=model_path)
    #datachunkは普通一つしかない
    with open(model_path, 'rb') as f:
        vrm_pydata.json, body_binary = parse_glb(f.read())
     
    #KHR_DRACO_MESH_COMPRESSION は対応してない場合落とさないといけないらしい。どのみち壊れたデータになるからね。
    if "extensionsRequired" in vrm_pydata.json:
        if "KHR_DRACO_MESH_COMPRESSION" in vrm_pydata.json["extensionsRequired"]:
            raise Exception("This VRM has DRACO COMPRESSION. This importer can't read this VRM. Draco圧縮されたVRMは未対応です")
    #改変不可ﾗｲｾﾝｽを撥ねる
    #CC_ND
    if re.match("CC(.*)ND(.*)", json_get(vrm_pydata.json,["extensions","VRM","meta","licenseName"],"")):
        raise Exception("This VRM is not allowed to Edit. CHECK ITS LICENSE　改変不可Licenseです。")
    #Vroidbhub licence
    if "otherPermissionUrl" in vrm_pydata.json["extensions"]["VRM"]["meta"]:
        from urllib.parse import parse_qsl,urlparse
        address = urlparse(vrm_pydata.json["extensions"]["VRM"]["meta"]["otherPermissionUrl"]).hostname
        if address is None:
            pass
        elif "vroid" in address :
            if dict(parse_qsl(vrm_pydata.json["extensions"]["VRM"]["meta"]["otherPermissionUrl"])).get("modification") == "disallow":
                raise Exception("This VRM is not allowed to Edit. CHECK ITS LICENSE　改変不可Licenseです。")
     #オリジナルライセンスに対する注意
    if vrm_pydata.json["extensions"][VRM_Types.VRM]["meta"]["licenseName"] == "Other":
        print("Is this VRM allowed to Edit? CHECK IT LICENSE")

    texture_rip(vrm_pydata,body_binary)

    vrm_pydata.decoded_binary = decode_bin(vrm_pydata.json,body_binary)

    mesh_read(vrm_pydata)
    material_read(vrm_pydata)
    skin_read(vrm_pydata)
    node_read(vrm_pydata)


    return vrm_pydata

def texture_rip(vrm_pydata,body_binary):
    bufferViews = vrm_pydata.json["bufferViews"]
    binary_reader = Binaly_Reader(body_binary)
    #ここ画像切り出し #blenderはバイト列から画像を読み込む術がないので、画像ファイルを書き出して、それを読み込むしかない。
    vrm_dir_path = os.path.dirname(os.path.abspath(vrm_pydata.filepath))
    if not "images" in vrm_pydata.json:
        return 
    for id,image_prop in enumerate(vrm_pydata.json["images"]):
        if "extra" in image_prop:
            image_name = image_prop["extra"]["name"]
        else :
            image_name = image_prop["name"]
        binary_reader.set_pos(bufferViews[image_prop["bufferView"]]["byteOffset"])
        image_binary = binary_reader.read_binaly(bufferViews[image_prop["bufferView"]]["byteLength"])
        image_type = image_prop["mimeType"].split("/")[-1]
        if image_name == "":
            image_name = "texture_" + str(id)
            print("no name image is named {}".format(image_name))
        elif len(image_name) >=50: 
            print("too long name image: {} is named {}".format(image_name,"tex_2longname_"+str(id)))
            image_name = "tex_2longname_"+str(id)

        def invalid_chars_remover(filename):
            unsafe_chars = {
             0: '\x00', 1: '\x01', 2: '\x02', 3: '\x03', 4: '\x04', 5: '\x05', 6: '\x06', 7: '\x07', 8: '\x08', 9: '\t', 10: '\n',\
             11: '\x0b', 12: '\x0c', 13: '\r', 14: '\x0e', 15: '\x0f', 16: '\x10', 17: '\x11', 18: '\x12', 19: '\x13', 20: '\x14',\
             21: '\x15', 22: '\x16', 23: '\x17', 24: '\x18', 25: '\x19', 26: '\x1a', 27: '\x1b', 28: '\x1c', 29: '\x1d', 30: '\x1e',\
             31: '\x1f', 34: '"', 42: '*', 47: '/', 58: ':', 60: '<', 62: '>', 63: '?', 92: '\\', 124: '|'
             } #32:space #33:! 
            remove_table = str.maketrans("","","".join([chr(charnum) for charnum in unsafe_chars.keys()]))
            safe_filename = filename.translate(remove_table)
            return safe_filename
        image_name = invalid_chars_remover(image_name)
        image_path = os.path.join(vrm_dir_path, image_name + "." + image_type)
        if not os.path.exists(image_path):#すでに同名の画像がある場合は基本上書きしない
            with open(image_path, "wb") as imageWriter:
                imageWriter.write(image_binary)
        elif image_name in [img.name for img in vrm_pydata.image_propaties]:#ただ、それがこのVRMを開いた時の名前の時はちょっと考えて書いてみる。
            written_flag = False
            for i in range(5):
                second_image_name = image_name+"_"+str(i)
                image_path = os.path.join(vrm_dir_path, second_image_name + "." + image_type)
                if not os.path.exists(image_path):
                    with open(image_path, "wb") as imageWriter:
                        imageWriter.write(image_binary)
                    image_name = second_image_name
                    written_flag = True
                    break
            if not written_flag:
                print("Thare are same name images more than 5 in folder. Failed to write file: {}".format(image_name))
        else:
            print(image_name + " Image is already exists. NOT OVER WRITTEN")
        image_propaty = VRM_Types.Image_props(image_name,image_path,image_type)
        vrm_pydata.image_propaties.append(image_propaty)

#　”accessorの順に”　データを読み込んでリストにしたものを返す
def decode_bin(json_data,binary):
    br = Binaly_Reader(binary)
    #This list indexed by accesser index
    decoded_binary = []
    bufferViews = json_data["bufferViews"]
    accessors = json_data["accessors"]
    type_num_dict = {"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}
    for accessor in accessors:
        type_num = type_num_dict[accessor["type"]]
        br.set_pos(bufferViews[accessor["bufferView"]]["byteOffset"])
        data_list = []
        for num in range(accessor["count"]):          
            if type_num == 1:
                data = br.read_as_dataType(accessor["componentType"])
            else:
                data = []
                for l in range(type_num):
                    data.append(br.read_as_dataType(accessor["componentType"]))
            data_list.append(data)
        decoded_binary.append(data_list)
        
    return decoded_binary

def mesh_read(vrm_pydata):
    #メッシュをパースする
    for n,mesh in enumerate(vrm_pydata.json["meshes"]):
        for j,primitive in enumerate(mesh["primitives"]):  
            vrm_mesh = VRM_Types.Mesh()
            vrm_mesh.object_id = n
            if j == 0:#mesh annotationとの兼ね合い
                vrm_mesh.name = mesh["name"]
            else :
                vrm_mesh.name = mesh["name"]+str(j)

            #region 頂点index
            if primitive["mode"] != GLC.TRIANGLES:
                #TODO その他ﾒｯｼｭﾀｲﾌﾟ対応
                raise Exception("unSupported polygon type(:{}) Exception".format(primitive["mode"]))
            vrm_mesh.face_indices = vrm_pydata.decoded_binary[primitive["indices"]]
            #3要素ずつに変換しておく(GCL.TRIANGLES前提なので)
            #ＡＴＴＥＮＴＩＯＮ　これだけndarray
            vrm_mesh.face_indices = numpy.reshape(vrm_mesh.face_indices, (-1, 3))
            #endregion 頂点index

            #ここから頂点属性
            vertex_attributes = primitive["attributes"]
            #頂点属性は実装によっては存在しない属性（例えばJOINTSやWEIGHTSがなかったりもする）もあるし、UVや頂点カラー0->Nで増やせる（ｽｷﾆﾝｸﾞは1要素(ﾎﾞｰﾝ4本)限定
            for attr in vertex_attributes.keys():
                vrm_mesh.__setattr__(attr,vrm_pydata.decoded_binary[vertex_attributes[attr]])

            #region TEXCOORD_FIX [ 古いuniVRM誤り: uv.y = -uv.y ->修復 uv.y = 1 - ( -uv.y ) => uv.y=1+uv.y]
            legacy_uv_flag = False #f***
            gen = json_get(vrm_pydata.json,["assets","generator"],"")
            if re.match("UniGLTF",gen):
                try:
                    if float("".join(gen[-4:])) < 1.16:
                        legacy_uv_flag = True
                except ValueError:
                    pass

            uv_count = 0
            while True:
                texcoordName = "TEXCOORD_{}".format(uv_count)
                if hasattr(vrm_mesh, texcoordName): 
                    texcoord = getattr(vrm_mesh,texcoordName)
                    for uv in texcoord:
                        if legacy_uv_flag:
                            uv[1] = 1 + uv[1]
                    uv_count +=1
                else:
                    break
            #blenderとは上下反対のuv,それはblenderに書き込むときに直す
            #endregion TEXCOORD_FIX

            #meshに当てられるマテリアルの場所を記録
            vrm_mesh.material_index = primitive["material"]

            #変換時のキャッシュ対応のためのデータ
            vrm_mesh.POSITION_accessor = primitive["attributes"]["POSITION"]
            
            #ここからモーフターゲット vrmのtargetは相対位置 normalは無視する
            if "targets" in primitive:
                morphTarget_point_list_and_accessor_index_dict = dict()
                for i,morphTarget in enumerate(primitive["targets"]):
                    posArray = vrm_pydata.decoded_binary[morphTarget["POSITION"]]
                    if "extra" in morphTarget:#for old AliciaSolid
                        #accesserのindexを持つのは変換時のキャッシュ対応のため
                        morphName = primitive["targets"][i]["extra"]["name"]
                    else:
                        morphName = primitive["extras"]["targetNames"][i]
                        #同上
                    morphTarget_point_list_and_accessor_index_dict[morphName] = [posArray,primitive["targets"][i]["POSITION"]]

                vrm_mesh.__setattr__("morphTarget_point_list_and_accessor_index_dict",morphTarget_point_list_and_accessor_index_dict)

            vrm_pydata.meshes.append(vrm_mesh)


    #ここからマテリアル
def material_read(vrm_pydata):
    VRM_EXTENSION_material_promaties = json_get(vrm_pydata.json,["extensions",VRM_Types.VRM,"materialProperties"],\
                                                default = [{"shader":"VRM_USE_GLTFSHADER"}]*len(vrm_pydata.json["materials"]))
    if "textures" in vrm_pydata.json:
        textures = vrm_pydata.json["textures"]
    for mat,ext_mat in zip(vrm_pydata.json["materials"],VRM_EXTENSION_material_promaties):
        vrm_pydata.materials.append(vrm2pydata_factory.material(mat,ext_mat,textures))



    #skinをパース　->バイナリの中身はskining実装の横着用
    #skinのjointsの(nodesの)indexをvertsのjoints_0は指定してる
    #inverseBindMatrices: 単にｽｷﾆﾝｸﾞするときの逆行列。読み込み不要なのでしない(自前計算もできる、めんどいけど)
    #ついでに[i][3]ではなく、[3][i]にマイナスx,y,zが入っている。　ここで詰まった。(出力時に)
    #joints:JOINTS_0の指定node番号のindex
def skin_read(vrm_pydata):
    for skin in vrm_pydata.json.get("skins",[]):
        vrm_pydata.skins_joints_list.append(skin["joints"])
        if "skeleton" in skin.keys():
            vrm_pydata.skins_root_node_list.append(skin["skeleton"])

            
    #node(ボーン)をﾊﾟｰｽする->親からの相対位置で記録されている
def node_read(vrm_pydata):
    for i,node in enumerate(vrm_pydata.json["nodes"]):
        vrm_pydata.nodes_dict[i] = vrm2pydata_factory.bone(node)
        #TODO こっからorigine_bone
        if "mesh" in node.keys():
            vrm_pydata.origine_nodes_dict[i] = [vrm_pydata.nodes_dict[i],node["mesh"]]
            if "skin" in node.keys():
                vrm_pydata.origine_nodes_dict[i].append(node["skin"])
            else:
                print(node["name"] + "is not have skin")



if "__main__" == __name__:
    model_path = "./AliciaSolid\\AliciaSolid.vrm"
    model_path = "./Vroid\\Vroid.vrm"
    read_vrm(model_path)
