from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["flow_db"]
grupos_col = db["grupos"]
denuncias_col = db["denuncias"]

# ✅ CONFIGURAÇÕES
CODIGO_VIP_SECRETO = os.getenv("CODIGO_VIP", "labareta444")
SENHA_ADM = os.getenv("SENHA_ADM", "admin123")
TEMPO_IMPULSIONAR = timedelta(hours=3)    # ⏰ 3 HORAS
TEMPO_VIP = timedelta(hours=24)           # ⏰ 24 HORAS VIP

@app.route("/")
def index():
    return render_template("index.html")

# ✅ GRUPOS ORDENADOS POR IMPULSO → VAI PRO TOPO!
@app.route("/grupos-dados")
def grupos_dados():
    try:
        cat = request.args.get("categoria", "Todos")
        filtro = {"ativo": True}
        if cat != "Todos":
            filtro["categoria"] = cat
        
        # Ordena: impulsionado recentemente primeiro → cai com o tempo
        grupos = list(grupos_col.find(filtro).sort([
            ("ultimo_impulso", -1),  # ⬆️ Quem impulsionou vai pro TOPO
            ("vip", -1),
            ("criado_em", -1)
        ]))
        
        agora = datetime.utcnow()
        for g in grupos:
            g["_id"] = str(g["_id"])
            # Verifica se VIP expirou
            if g.get("vip_ate") and agora > g["vip_ate"]:
                g["vip"] = False
            # Tempo restante do impulso
            ultimo = g.get("ultimo_impulso")
            if ultimo:
                proximo = ultimo + TEMPO_IMPULSIONAR
                g["pode_impulsionar"] = agora >= proximo
                g["tempo_restante_impulso"] = int((proximo - agora).total_seconds()) if not g["pode_impulsionar"] else 0
            else:
                g["pode_impulsionar"] = True
                g["tempo_restante_impulso"] = 0
            # Tempo restante VIP
            vip_ate = g.get("vip_ate")
            if vip_ate:
                g["tempo_restante_vip"] = int((vip_ate - agora).total_seconds())
                g["vip_ativo"] = agora < vip_ate
            else:
                g["tempo_restante_vip"] = 0
                g["vip_ativo"] = False
        
        return jsonify(grupos)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/clicar/<grupo_id>", methods=["POST"])
def clicar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not uid:
        return jsonify({"erro": "Sem ID"}), 400
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    
    try:
        chave_clique = f"clique:{uid}:{grupo_id}"
        ja_contado = db.cliques.find_one({"_id": chave_clique})
        if ja_contado:
            return jsonify({"sucesso": "Contado anteriormente"})
        db.cliques.insert_one({"_id": chave_clique, "tempo": datetime.utcnow()})
        grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
        return jsonify({"sucesso": True})
    except Exception as e:
        grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$inc": {"cliques": 1}})
        return jsonify({"sucesso": True, "aviso": "Clique contado"})

# ✅ VALIDA LINK COMPLETO + SEM REPETIÇÃO
@app.route("/enviar-grupo", methods=["POST"])
def enviar_grupo():
    dados = request.form
    link = dados.get("link", "").strip()
    nome = dados.get("nome", "").strip()
    categoria = dados.get("categoria", "Outros")
    foto = dados.get("foto_base64", "")
    codigo = dados.get("codigo_adm", "").strip()
    uid = request.headers.get("X-Usuario-ID", "")

    if not link or not nome:
        return jsonify({"erro": "Preencha link e nome!"}), 400

    # ✅ LINK COMPLETO OBRIGATÓRIO
    if link == "https://chat.whatsapp.com/" or link == "http://chat.whatsapp.com/":
        return jsonify({"erro": "❌ Link INVÁLIDO! Use o link COMPLETO com o código no final!\nEx: https://chat.whatsapp.com/K7ai1KeLMiZCsaZ3ni04Zq"}), 400
    
    # ✅ VALIDA FORMATO DO LINK
    if not link.startswith("https://chat.whatsapp.com/") or len(link) < 50:
        return jsonify({"erro": "❌ Link INVÁLIDO! Copie o link completo do grupo!"}), 400

    # ✅ SEM LINKS REPETIDOS
    existe = grupos_col.find_one({"link": link, "ativo": True})
    if existe:
        return jsonify({"erro": "❌ Esse link JÁ ESTÁ CADASTRADO!"}), 400

    # ✅ CÓDIGO ERRADO
    if codigo and codigo != CODIGO_VIP_SECRETO:
        return jsonify({"erro": "❌ Código VIP INVÁLIDO"}), 400

    # ✅ CÓDIGO CORRETO → GRÁTIS + VIP 24h
    if codigo and codigo == CODIGO_VIP_SECRETO:
        agora = datetime.utcnow()
        novo_grupo = {
            "link": link, "nome": nome, "categoria": categoria, "foto": foto,
            "usuario_id": uid, "cliques": 0, "ativo": True,
            "vip": True, "vip_ate": agora + TEMPO_VIP,
            "ultimo_impulso": agora,  # ⬆️ JÁ VAI PRO TOPO
            "criado_em": agora
        }
        grupos_col.insert_one(novo_grupo)
        return jsonify({"sucesso": "✅ Grupo enviado GRÁTIS! VIP por 24h!", "sem_pix": True})

    # ✅ SEM CÓDIGO → GERA PIX
    codigo_pix = f"00020126580014br.gov.bcb.pix0104FLOW{os.urandom(7).hex().upper()}5204000053039865802BR5904FLOW6007RIO62070503***6304"
    return jsonify({"codigo_pix": codigo_pix})

# ✅ MEUS GRUPOS COM TEMPO REAL
@app.route("/meus-grupos")
def meus_grupos():
    uid = request.headers.get("X-Usuario-ID", "")
    agora = datetime.utcnow()
    grupos = list(grupos_col.find({"usuario_id": uid}).sort("ultimo_impulso", -1))
    
    for g in grupos:
        g["_id"] = str(g["_id"])
        # Verifica VIP expirado
        if g.get("vip_ate") and agora > g["vip_ate"]:
            g["vip"] = False
        # Tempo impulso
        ultimo = g.get("ultimo_impulso")
        if ultimo:
            proximo = ultimo + TEMPO_IMPULSIONAR
            g["pode_impulsionar"] = agora >= proximo
            if not g["pode_impulsionar"]:
                g["proximo_impulso_segundos"] = int((proximo - agora).total_seconds())
        else:
            g["pode_impulsionar"] = True
        # Tempo VIP restante
        if g.get("vip_ate") and g.get("vip", False):
            g["vip_restante_segundos"] = int((g["vip_ate"] - agora).total_seconds())
        else:
            g["vip_restante_segundos"] = 0
    
    return jsonify(grupos)

# ✅ IMPULSIONAR GRÁTIS → 3h DE ESPERA
@app.route("/impulsionar/<grupo_id>", methods=["POST"])
def impulsionar(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    if not grupo:
        return jsonify({"erro": "Não encontrado"}), 404
    
    # ⏰ VERIFICA 3 HORAS
    ultimo = grupo.get("ultimo_impulso")
    if ultimo and (datetime.utcnow() - ultimo) < TEMPO_IMPULSIONAR:
        proximo = ultimo + TEMPO_IMPULSIONAR
        espera = int((proximo - datetime.utcnow()).total_seconds())
        return jsonify({
            "erro": f"⏰ Aguarde 3h! Próximo impulso em {espera//3600}h {(espera%3600)//60}min",
            "espera_segundos": espera
        }), 429
    
    # ⬆️ IMPULSIONA → VAI PRO TOPO DA LISTA
    grupos_col.update_one(
        {"_id": ObjectId(grupo_id)},
        {"$set": {"ultimo_impulso": datetime.utcnow()}}
    )
    return jsonify({"sucesso": "✅ Impulsionado! ⬆️ Grupo foi pro TOPO!"})

# ✅ IMPULSIONAR VIP → R$5,00 = 24h NO TOPO + SELA VERIFICADA
@app.route("/impulsionar-vip/<grupo_id>", methods=["POST"])
def impulsionar_vip(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    
    grupo = grupos_col.find_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    if not grupo:
        return jsonify({"erro": "Não encontrado"}), 404
    
    # Se já tem VIP ativo → não deixa impulsionar de novo
    if grupo.get("vip_ate") and datetime.utcnow() < grupo["vip_ate"]:
        restante = int((grupo["vip_ate"] - datetime.utcnow()).total_seconds())
        return jsonify({
            "erro": f"⭐ JÁ É VIP! Válido por mais {restante//3600}h",
            "ja_vip": True,
            "restante_segundos": restante
        }), 400
    
    # Gera PIX de R$5,00 para VIP 24h
    codigo_pix = f"00020126580014br.gov.bcb.pix0104FLOW{os.urandom(7).hex().upper()}5204000053039865802BR5904FLOW6007RIO62070503***6304"
    return jsonify({
        "codigo_pix": codigo_pix,
        "valor": "R$ 5,00",
        "duracao_horas": 24,
        "mensagem": "💳 Pague R$5,00 e seu grupo fica VIP por 24h!"
    })

# ✅ CONFIRMAÇÃO VIP (chamado após pagamento)
@app.route("/confirmar-vip/<grupo_id>", methods=["POST"])
def confirmar_vip(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    
    agora = datetime.utcnow()
    grupos_col.update_one(
        {"_id": ObjectId(grupo_id), "usuario_id": uid},
        {"$set": {
            "vip": True,
            "vip_ate": agora + TEMPO_VIP,
            "ultimo_impulso": agora  # ⬆️ VAI PRO TOPO TAMBÉM!
        }}
    )
    return jsonify({"sucesso": "⭐ VIP ATIVADO! 24h em destaque!"})

@app.route("/apagar-grupo/<grupo_id>", methods=["POST"])
def apagar_grupo(grupo_id):
    uid = request.headers.get("X-Usuario-ID", "")
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    grupos_col.delete_one({"_id": ObjectId(grupo_id), "usuario_id": uid})
    return jsonify({"sucesso": "✅ Apagado!"})

@app.route("/denunciar/<grupo_id>", methods=["POST"])
def denunciar(grupo_id):
    dados = request.json
    denuncias_col.insert_one({
        "grupo_id": grupo_id, "motivo": dados.get("motivo", ""),
        "denunciado_em": datetime.utcnow(), "lida": False
    })
    return jsonify({"sucesso": "✅ Denunciado!"})

def verificar_senha_adm():
    senha_recebida = (request.headers.get("X-Adm-Senha") or "").strip()
    return senha_recebida == SENHA_ADM

@app.route("/adm/grupos")
def adm_grupos():
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    todos = list(grupos_col.find().sort("criado_em", -1))
    for g in todos:
        g["_id"] = str(g["_id"])
        g["ativo"] = g.get("ativo", True)
    return jsonify(todos)

@app.route("/adm/denuncias")
def adm_denuncias():
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    den = list(denuncias_col.find({"lida": False}).sort("denunciado_em", -1))
    for d in den:
        d["_id"] = str(d["_id"])
    return jsonify(den)

@app.route("/adm/desativar/<grupo_id>", methods=["POST"])
def adm_desativar(grupo_id):
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    if not ObjectId.is_valid(grupo_id):
        return jsonify({"erro": "ID inválido"}), 400
    grupos_col.update_one({"_id": ObjectId(grupo_id)}, {"$set": {"ativo": False}})
    return jsonify({"sucesso": "✅ Desativado!"})

@app.route("/adm/marcar-lida/<denuncia_id>", methods=["POST"])
def adm_marcar_lida(denuncia_id):
    if not verificar_senha_adm():
        return jsonify({"erro": "SENHA ERRADA"}), 403
    if not ObjectId.is_valid(denuncia_id):
        return jsonify({"erro": "ID inválido"}), 400
    denuncias_col.update_one({"_id": ObjectId(denuncia_id)}, {"$set": {"lida": True}})
    return jsonify({"sucesso": "✅ Lida!"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
