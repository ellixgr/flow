from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# 🚨 SÓ PEGA DAS VARIÁVEIS DO RENDER — NENHUM VALOR ESCRITO AQUI!
MONGO_URI = os.getenv("MONGO_URI")
CODIGO_VIP_SECRETO = os.getenv("CODIGO_VIP")  # COLOCA NO RENDER: labareta444
SENHA_ADM = os.getenv("SENHA_ADM")            # COLOCA SUA SENHA FORTE NO RENDER!
TEMPO_IMPULSIONAR = timedelta(hours=3)

# ✅ PLANOS VIP (APENAS VALORES DE PREÇO/TEMPO, SEM SEGREDO)
PLANOS_VIP = {
    "5": {"valor": 5.00, "dias": 1, "nome": "R$ 5,00 → 1 Dia VIP"},
    "10": {"valor": 10.00, "dias": 2, "nome": "R$ 10,00 → 2 Dias VIP"},
    "30": {"valor": 30.00, "dias": 3, "nome": "R$ 30,00 → 3 Dias VIP"},
    "100": {"valor": 100.00, "dias": 30, "nome": "🎁 R$ 100,00 → 1 MÊS VIP"}
}

# CONEXÃO BANCO
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["flow_db"]
grupos_col = db["grupos"]
denuncias_col = db["denuncias"]
cliques_col = db["cliques"]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/grupos-dados")
def grupos_dados():
    try:
        cat = request.args.get("categoria", "Todos")
        filtro = {"ativo": True}
        if cat != "Todos":
            filtro["categoria"] = cat
        
        grupos = list(grupos_col.find(filtro).sort([
            ("ultimo_impulso", -1), ("vip", -1), ("criado_em", -1)
        ]))
        
        agora = datetime.utcnow()
        uid = request.headers.get("X-Usuario-ID", "")
        
        for g in grupos:
            g["_id"] = str(g["_id"])
            dono_grupo = g.get("usuario_id", "")
            g["cliques"] = g.get("cliques", 0)

            if g.get("vip_ate") and agora < g["vip_ate"]:
                g["vip_ativo"] = True
                g["vip_restante_segundos"] = int((g["vip_ate"] - agora).total_seconds())
            else:
                g["vip_ativo"] = False
                g["vip_restante_segundos"] = 0
                g["vip"] = False

            if dono_grupo and uid and dono_grupo == uid:
                ultimo = g.get("ultimo_impulso")
                if ultimo:
                    proximo = ultimo + TEMPO_IMPULSIONAR
                    g["pode_impulsionar"] = agora >= proximo
                    g["tempo_restante_impulso"] = int((proximo - agora).total_seconds()) if not g["pode_impulsionar"] else 0
                else:
                    g["pode_impulsionar"] = True
                    g["tempo_restante_impulso"] = 0
            else:
                g["pode_impulsionar"] = None
                g["tempo_restante_impulso"] = None
        
        return jsonify(grupos)
    except Exception as e:
        print("ERRO grupos-dados:", str(e))
        return jsonify([]), 200

@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not uid or not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    try:
        chave = f"{uid}||{grupo_id}"
        if not cliques_col.find_one({"chave": chave}):
            cliques_col.insert_one({"chave": chave, "data": datetime.utcnow()})
            grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
        return jsonify({"sucesso": True})
    except Exception as e:
        print("ERRO clique:", str(e))
        return jsonify({"sucesso": True})

@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    try:
        dados = request.form
        link = dados.get("link", "").strip()
        nome = dados.get("nome", "").strip()
        categoria = dados.get("categoria", "Outros")
        foto = dados.get("foto_base64", "")
        codigo = dados.get("codigo_adm", "").strip()
        uid = request.headers.get("X-Usuario-ID", "")

        if not link or not nome:
            return jsonify({"erro": "Preencha link e nome!"}), 400
        if not link.startswith("https://chat.whatsapp.com/"):
            return jsonify({"erro": "❌ Link INVÁLIDO!"}), 400
        if grupos_col.find_one({"link": link, "ativo": True}):
            return jsonify({"erro": "❌ Esse link JÁ ESTÁ CADASTRADO!"}), 400

        agora = datetime.utcnow()
        
        # COMPARA COM A VARIÁVEL DO RENDER — NÃO ESTÁ ESCRITO AQUI!
        if CODIGO_VIP_SECRETO and codigo == CODIGO_VIP_SECRETO:
            novo_grupo = {
                "link": link, "nome": nome, "categoria": categoria, "foto": foto,
                "usuario_id": uid, "cliques": 0, "ativo": True,
                "vip": True, "vip_ate": agora + timedelta(days=1),
                "ultimo_impulso": agora, "criado_em": agora
            }
            grupos_col.insert_one(novo_grupo)
            return jsonify({"sucesso": "✅ Grupo enviado GRÁTIS! VIP por 24h!", "sem_pix": True})

        plano = PLANOS_VIP.get(dados.get("plano","5"))
        codigo_pix = f"00020126580014br.gov.bcb.pix0104FLOW{os.urandom(7).hex().upper()}5204000053039865802BR5904FLOW6007RIO62070503***6304"
        
        novo_grupo = {
            "link": link, "nome": nome, "categoria": categoria, "foto": foto,
            "usuario_id": uid, "cliques": 0, "ativo": True,
            "vip": False, "vip_ate": None,
            "ultimo_impulso": agora, "criado_em": agora
        }
        grupos_col.insert_one(novo_grupo)
        return jsonify({"codigo_pix": codigo_pix, "valor": plano["valor"], "dias_vip": plano["dias"]})
    
    except Exception as e:
        print("ERRO enviar:", str(e))
        return jsonify({"erro": str(e)}), 500

@app.route("/meus-grupos")
def meus_grupos():
    uid = request.headers.get("X-Usuario-ID", "")
    if not uid: return jsonify([])
    try:
        agora = datetime.utcnow()
        grupos = list(grupos_col.find({"usuario_id": uid}).sort("ultimo_impulso", -1))
        for g in grupos:
            g["_id"] = str(g["_id"])
            g["cliques"] = g.get("cliques", 0)
            if g.get("vip_ate") and agora < g["vip_ate"]:
                g["vip_ativo"] = True
                g["vip_restante_segundos"] = int((g["vip_ate"] - agora).total_seconds())
            else:
                g["vip_ativo"] = False
                g["vip_restante_segundos"] = 0
                g["vip"] = False
            ultimo = g.get("ultimo_impulso")
            if ultimo:
                proximo = ultimo + TEMPO_IMPULSIONAR
                g["pode_impulsionar"] = agora >= proximo
                if not g["pode_impulsionar"]:
                    g["proximo_impulso_segundos"] = int((proximo - agora).total_seconds())
            else:
                g["pode_impulsionar"] = True
        return jsonify(grupos)
    except Exception as e:
        print("ERRO meus:", str(e))
        return jsonify([])

@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not ObjectId.is_valid(grupo_id): return jsonify({"erro":"ID inválido"}),400
    grupo = grupos_col.find_one({"_id":ObjectId(grupo_id),"usuario_id":uid})
    if not grupo: return jsonify({"erro":"Não seu"}),403
    ultimo = grupo.get("ultimo_impulso")
    if ultimo and (datetime.utcnow()-ultimo) < TEMPO_IMPULSIONAR:
        espera = int((ultimo+TEMPO_IMPULSIONAR - datetime.utcnow()).total_seconds())
        return jsonify({"erro":f"Aguarde {espera//3600}h {(espera%3600)//60}min"}),429
    grupos_col.update_one({"_id":ObjectId(grupo_id)},{"$set":{"ultimo_impulso":datetime.utcnow()}})
    return jsonify({"sucesso":True})

@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    uid = request.headers.get("X-Usuario-ID","")
    grupos_col.delete_one({"_id":ObjectId(grupo_id),"usuario_id":uid})
    cliques_col.delete_many({"grupo_id":grupo_id})
    return jsonify({"sucesso":True})

@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados=request.json
    denuncias_col.insert_one({
        "grupo_id":grupo_id,"motivo":dados.get("motivo",""),
        "data":datetime.utcnow(),"lida":False
    })
    return jsonify({"sucesso":True})

# 🔐 PAINEL ADM — SÓ FUNCIONA COM A SENHA DO RENDER, NÃO ESTÁ AQUI ESCRITA!
def verificar_senha():
    recebida = (request.headers.get("X-Adm-Senha") or "").strip()
    return SENHA_ADM and recebida == SENHA_ADM

@app.route("/adm/grupos")
def adm_grupos():
    if not verificar_senha(): return jsonify({"erro":"SENHA ERRADA"}),403
    todos = list(grupos_col.find().sort("criado_em",-1))
    for g in todos: g["_id"]=str(g["_id"]);g["ativo"]=g.get("ativo",True);g["cliques"]=g.get("cliques",0)
    return jsonify(todos)

@app.route("/adm/denuncias")
def adm_denuncias():
    if not verificar_senha(): return jsonify({"erro":"SENHA ERRADA"}),403
    den = list(denuncias_col.find({"lida":False}).sort("data",-1))
    for d in den: d["_id"]=str(d["_id"])
    return jsonify(den)

@app.route("/adm/desativar/<grupo_id>", methods=["POST"])
def adm_desativar(grupo_id):
    if not verificar_senha(): return jsonify({"erro":"SENHA ERRADA"}),403
    grupos_col.update_one({"_id":ObjectId(grupo_id)},{"$set":{"ativo":False}})
    return jsonify({"sucesso":True})

@app.route("/escolher-plano-vip/<grupo_id>", methods=["POST"])
def escolher_plano_vip(grupo_id):
    uid = request.headers.get("X-Usuario-ID","")
    if not ObjectId.is_valid(grupo_id): return jsonify({"erro":"ID inválido"}),400
    grupo = grupos_col.find_one({"_id":ObjectId(grupo_id),"usuario_id":uid})
    if not grupo: return jsonify({"erro":"Não encontrado"}),404
    dados=request.json or {}
    plano = PLANOS_VIP.get(dados.get("plano","5"))
    codigo_pix = f"00020126580014br.gov.bcb.pix0104FLOW{os.urandom(7).hex().upper()}5204000053039865802BR5904FLOW6007RIO62070503***6304"
    return jsonify({"codigo_pix":codigo_pix,"valor":plano["valor"],"dias_vip":plano["dias"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
