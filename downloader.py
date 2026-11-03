import os
import uuid
import time
import yt_dlp
import requests
from flask import request, jsonify, send_file, render_template_string

def registrar_rotas_downloader(app, db, MP_TOKEN):
    colecao_downloads = db["downloads_usuarios"]
    colecao_vip = db["usuarios_vip"]
    colecao_pagamentos = db["pagamentos_pendentes"]

    @app.route('/msc')
    def pagina_download():
        html_msc = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FLOW — Baixar Músicas e Vídeos</title>
    <style>
        :root {
            --primary: #25d366;
            --dark-bg: #0d1117;
            --card-bg: #161b22;
            --text: #f0f6fc;
            --border: #30363d;
            --danger: #ff4d4d;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; }
        body {
            background-color: var(--dark-bg);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            width: 100%;
            max-width: 500px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
            text-align: center;
        }
        h1 { font-size: 22px; color: var(--primary); margin-bottom: 8px; font-weight: 800; }
        p { font-size: 13px; color: #8b949e; margin-bottom: 20px; }
        
        input[type="text"] {
            width: 100%;
            padding: 14px;
            background: #0d1117;
            border: 1px solid var(--border);
            border-radius: 12px;
            color: #fff;
            font-size: 15px;
            margin-bottom: 15px;
            outline: none;
            text-align: center;
        }
        input[type="text"]:focus { border-color: var(--primary); }

        .botoes-acao {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
        }
        button {
            flex: 1;
            padding: 14px;
            border: none;
            border-radius: 12px;
            font-weight: bold;
            font-size: 14px;
            cursor: pointer;
            transition: opacity 0.2s, transform 0.1s;
        }
        button:hover { opacity: 0.9; transform: scale(1.02); }
        .btn-audio { background: #1f6feb; color: #fff; }
        .btn-video { background: var(--primary); color: #000; }
        .btn-voltar {
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid var(--border);
            width: 100%;
            padding: 10px;
            border-radius: 10px;
            font-size: 13px;
            cursor: pointer;
            margin-top: 10px;
        }
        .btn-vip {
            background: linear-gradient(135deg, #ffd700, #ff8c00);
            color: #000;
            width: 100%;
            padding: 12px;
            border-radius: 10px;
            font-weight: bold;
            font-size: 14px;
            cursor: pointer;
            margin-bottom: 15px;
        }

        #statusMsg {
            margin-top: 15px;
            font-size: 13px;
            color: #8b949e;
        }
        .loading { color: #ffd700 !important; font-weight: bold; }
        .bloqueado { opacity: 0.5; pointer-events: none; }
        
        /* ESTILO DO PREVIEW */
        #previewBox {
            display: none;
            margin-top: 15px;
            background: #0d1117;
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 15px;
            text-align: center;
        }
        #previewImg {
            width: 100%;
            max-height: 180px;
            object-fit: cover;
            border-radius: 10px;
            margin-bottom: 10px;
        }
        #previewTitle {
            font-size: 13px;
            font-weight: 600;
            color: #f0f6fc;
            margin-bottom: 12px;
        }

        #vipModal {
            display: none;
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.8);
            justify-content: center;
            align-items: center;
            padding: 20px;
            z-index: 999;
        }
        .modal-content {
            background: var(--card-bg);
            border: 1px solid var(--border);
            padding: 20px;
            border-radius: 16px;
            max-width: 400px;
            width: 100%;
            text-align: center;
        }
    </style>
</head>
<body>

<div class="container">
    <h1>📥 FLOW Downloader</h1>
    <p id="infoLimite">Verificando seus downloads gratuitos...</p>

    <div id="areaBusca">
        <input type="text" id="termoInput" placeholder="Ex: Nome da música ou link...">

        <div class="botoes-acao" id="botoesBusca">
            <button class="btn-audio" onclick="prepararDownload('audio')">🎵 Buscar MP3</button>
            <button class="btn-video" onclick="prepararDownload('video')">🎬 Buscar MP4</button>
        </div>
    </div>

    <!-- CAIXA DE PREVIEW DA MÍDIA -->
    <div id="previewBox">
        <img id="previewImg" src="" alt="Capa da Mídia">
        <p id="previewTitle"></p>
        <p style="font-size: 12px; color: #ffd700; margin-bottom: 10px;">É esta mídia que deseja baixar?</p>
        <div class="botoes-acao">
            <button class="btn-video" onclick="confirmarDownload(true)">✅ Sim</button>
            <button class="btn-voltar" onclick="confirmarDownload(false)" style="margin-top:0; background:var(--danger); color:#fff; border:none;">❌ Não</button>
        </div>
    </div>

    <button class="btn-vip" onclick="abrirModalVip()">👑 Seja VIP (R$ 10/mês - 20 mídias/dia)</button>
    <button class="btn-voltar" onclick="window.location.href='/'">⬅️ Voltar para o Site Principal</button>

    <div id="statusMsg"></div>
</div>

<div id="vipModal">
    <div class="modal-content">
        <h2>👑 Assinar Plano VIP</h2>
        <p>Tenha 20 downloads por dia por apenas R$ 10,00/mês.</p>
        <div id="pixContainer" style="margin: 15px 0;">
            <button class="btn-audio" onclick="gerarPixVip()">Gerar Pix de R$ 10,00</button>
        </div>
        <div id="pixInfo" style="display:none;">
            <p style="font-size: 12px; color: #ffd700; margin-bottom: 8px;">Copie e cole o código Pix abaixo no seu banco:</p>
            <textarea id="copiaColaPix" rows="3" readonly style="width:100%; background:#0d1117; color:#fff; border:1px solid var(--border); border-radius:8px; padding:8px; font-size:11px;"></textarea>
            <button class="btn-video" style="margin-top: 10px;" onclick="verificarPagamentoVip()">🔄 Já paguei / Verificar</button>
        </div>
        <button class="btn-voltar" onclick="fecharModalVip()" style="margin-top:15px;">Fechar</button>
    </div>
</div>

<script>
let usuarioId = localStorage.getItem('flow_user_id');
if (!usuarioId) {
    usuarioId = 'user_' + Math.random().toString(36).substring(2) + Date.now();
    localStorage.setItem('flow_user_id', usuarioId);
}

let pagamentoIdAtual = null;
let dadosPendentes = null;

async function checarStatus() {
    try {
        let res = await fetch(`/api/verificar-limite?usuario_id=${usuarioId}`);
        let data = await res.json();
        let info = document.getElementById('infoLimite');
        if (data.vip) {
            info.innerHTML = `👑 Conta VIP Ativa! Restam <b style="color:var(--primary);">${data.restantes}</b> downloads hoje.`;
        } else {
            info.innerHTML = `🎁 Downloads grátis restantes: <b style="color:var(--primary);">${data.restantes} / 3</b>`;
            if (data.restantes <= 0) {
                document.getElementById('botoesBusca').classList.add('bloqueado');
                info.innerHTML = `<span style="color:var(--danger);">⚠️ Limite gratuito esgotado! Seja VIP para continuar.</span>`;
            }
        }
    } catch(e) { console.error(e); }
}
checarStatus();

async function prepararDownload(tipo) {
    let termo = document.getElementById('termoInput').value.trim();
    let statusDiv = document.getElementById('statusMsg');
    if(!termo) { alert("Por favor, digite um nome ou cole um link!"); return; }

    statusDiv.className = "loading";
    statusDiv.innerText = "🔍 Buscando informações e capa da mídia...";

    try {
        let res = await fetch('/api/adm/preview-midia', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ usuario_id: usuarioId, termo: termo })
        });

        let data = await res.json();
        if (!res.ok) throw new Error(data.erro || "Erro ao buscar mídia");

        dadosPendentes = { tipo: tipo, termo: termo };
        
        document.getElementById('previewImg').src = data.thumbnail;
        document.getElementById('previewTitle').innerText = data.title;
        document.getElementById('previewBox').style.display = 'block';
        document.getElementById('areaBusca').style.display = 'none';
        statusDiv.innerText = "";
    } catch(err) {
        statusDiv.className = "";
        statusDiv.style.color = "var(--danger)";
        statusDiv.innerText = "❌ Erro: " + err.message;
    }
}

async function confirmarVideo(confirmado) {
    if (!confirmado) {
        document.getElementById('previewBox').style.display = 'none';
        document.getElementById('areaBusca').style.display = 'block';
        document.getElementById('statusMsg').innerText = "";
        return;
    }

    let tipo = dadosPendentes.tipo;
    let termo = dadosPendentes.termo;
    let statusDiv = document.getElementById('statusMsg');

    document.getElementById('previewBox').style.display = 'none';
    statusDiv.className = "loading";
    statusDiv.innerText = "⏳ A processar e a preparar o download... Aguarde!";

    let rota = tipo === 'audio' ? '/api/adm/baixar-audio' : '/api/adm/baixar-video';

    try {
        let res = await fetch(rota, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ usuario_id: usuarioId, termo: termo })
        });

        if (!res.ok) {
            let errData = await res.json();
            throw new Error(errData.erro || "Erro ao baixar arquivo");
        }

        let disposition = res.headers.get('content-disposition');
        let filename = "arquivo";
        if (disposition && disposition.includes('filename=')) {
            let match = disposition.match(/filename="?([^"]+)"?/);
            if (match && match[1]) filename = decodeURIComponent(match[1]);
        }

        let blob = await res.blob();
        let url = window.URL.createObjectURL(blob);
        let a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();

        statusDiv.className = "";
        statusDiv.style.color = "var(--primary)";
        statusDiv.innerText = "✅ Download concluído com sucesso!";
        document.getElementById('areaBusca').style.display = 'block';
        checarStatus();
    } catch(err) {
        console.error(err);
        statusDiv.className = "";
        statusDiv.style.color = "var(--danger)";
        statusDiv.innerText = "❌ Erro: " + err.message;
        document.getElementById('areaBusca').style.display = 'block';
        checarStatus();
    }
}

// Atalho para a função do botão de confirmação
function confirmarDownload(sim) {
    confirmarVideo(sim);
}

function abrirModalVip() { document.getElementById('vipModal').style.display = 'flex'; }
function fecharModalVip() { document.getElementById('vipModal').style.display = 'none'; }

async function gerarPixVip() {
    try {
        let res = await fetch('/api/criar-vip-pix', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ usuario_id: usuarioId })
        });
        let data = await res.json();
        if(data.pix_code) {
            pagamentoIdAtual = data.payment_id;
            document.getElementById('copiaColaPix').value = data.pix_code;
            document.getElementById('pixInfo').style.display = 'block';
        } else { alert("Erro ao gerar Pix: " + (data.erro || 'Desconhecido')); }
    } catch(e) { alert("Erro de conexão ao gerar Pix."); }
}

async function verificarPagamentoVip() {
    if(!pagamentoIdAtual) return;
    try {
        let res = await fetch(`/api/verificar-vip-pix?id=${pagamentoIdAtual}&usuario_id=${usuarioId}`);
        let data = await res.json();
        if(data.status === 'approved') {
            alert("🎉 Pagamento aprovado! Seu plano VIP foi ativado com sucesso.");
            fecharModalVip();
            checarStatus();
            location.reload();
        } else { alert("⏳ Pagamento ainda não confirmado. Conclua o Pix no seu banco."); }
    } catch(e) { alert("Erro ao verificar pagamento."); }
}
</script>
</body>
</html>"""
        return render_template_string(html_msc)

    @app.route('/api/verificar-limite', methods=['GET'])
    def verificar_limite():
        usuario_id = request.args.get("usuario_id")
        hoje = time.strftime("%Y-%m-%d")
        vip_info = colecao_vip.find_one({"usuario_id": usuario_id, "expira_em": {"$gt": time.time()}})
        if vip_info:
            qtd_hoje = vip_info.get("usados_hoje", {}).get(hoje, 0)
            return jsonify({"vip": True, "restantes": max(0, 20 - qtd_hoje)})
        reg = colecao_downloads.find_one({"usuario_id": usuario_id}) or {"total_baixados": 0}
        return jsonify({"vip": False, "restantes": max(0, 3 - reg.get("total_baixados", 0))})

    @app.route('/api/criar-vip-pix', methods=['POST'])
    def criar_vip_pix():
        data = request.json or {}
        usuario_id = data.get("usuario_id")
        if not usuario_id: return jsonify({"erro": "ID inválido"}), 400

        headers = {"Authorization": f"Bearer {MP_TOKEN}", "Content-Type": "application/json", "X-Idempotency-Key": str(uuid.uuid4())}
        payload = {"transaction_amount": 10.00, "description": "VIP Flow Downloader", "payment_method_id": "pix", "payer": {"email": f"vip_{int(time.time())}@flowsite.com"}}
        try:
            r = requests.post("https://api.mercadopago.com/v1/payments", json=payload, headers=headers, timeout=15)
            if r.status_code == 201:
                res = r.json()
                pid = str(res["id"])
                colecao_pagamentos.insert_one({"payment_id": pid, "usuario_id": usuario_id, "tipo": "vip", "ativado": False, "criado_em": time.time()})
                return jsonify({"payment_id": pid, "pix_code": res.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code", "")})
        except Exception as e: print(e)
        return jsonify({"erro": "Falha ao gerar Pix"}), 500

    @app.route('/api/verificar-vip-pix', methods=['GET'])
    def verificar_vip_pix():
        pid, usuario_id = request.args.get("id"), request.args.get("usuario_id")
        status = "pending"
        try:
            r = requests.get(f"https://api.mercadopago.com/v1/payments/{pid}", headers={"Authorization": f"Bearer {MP_TOKEN}"}, timeout=10)
            if r.status_code == 200:
                d = r.json()
                status = d.get("status", "pending")
                if status == "approved":
                    pendente = colecao_pagamentos.find_one({"payment_id": str(pid)})
                    if pendente and not pendente.get("ativado"):
                        colecao_vip.update_one({"usuario_id": usuario_id}, {"$set": {"expira_em": time.time() + (30*86400), "usados_hoje": {}}}, upsert=True)
                        colecao_pagamentos.update_one({"payment_id": str(pid)}, {"$set": {"ativado": True}})
        except Exception as e: print(e)
        return jsonify({"status": status})

    def checar_permissao(usuario_id):
        hoje = time.strftime("%Y-%m-%d")
        vip = colecao_vip.find_one({"usuario_id": usuario_id, "expira_em": {"$gt": time.time()}})
        if vip:
            if vip.get("usados_hoje", {}).get(hoje, 0) >= 20: 
                return False, "Limite VIP diário atingido!"
            return True, "vip"
        
        reg = colecao_downloads.find_one({"usuario_id": usuario_id}) or {"total_baixados": 0}
        if reg.get("total_baixados", 0) >= 3: 
            return False, "Limite gratuito esgotado! Assine o VIP por R$ 10/mês."
        return True, "gratuito"

    def registrar_sucesso_download(usuario_id, tipo_conta):
        hoje = time.strftime("%Y-%m-%d")
        if tipo_conta == "vip":
            vip = colecao_vip.find_one({"usuario_id": usuario_id})
            usados = vip.get("usados_hoje", {}) if vip else {}
            usados[hoje] = usados.get(hoje, 0) + 1
            colecao_vip.update_one({"usuario_id": usuario_id}, {"$set": {"usados_hoje": usados}})
        else:
            colecao_downloads.update_one({"usuario_id": usuario_id}, {"$inc": {"total_baixados": 1}}, upsert=True)

    # ROTA DE PREVIEW (BUSCA OS DADOS SEM BAIXAR NEM DESCONTAR CRÉDITO)
    @app.route('/api/adm/preview-midia', methods=['POST'])
    def adm_preview_midia():
        data = request.json or {}
        usuario_id, termo = data.get("usuario_id"), data.get("termo", "").strip()
        if not usuario_id: return jsonify({"erro": "ID obrigatório"}), 400
        
        permitido, msg = checar_permissao(usuario_id)
        if not permitido: return jsonify({"erro": msg}), 403
        if not termo: return jsonify({"erro": "Termo vazio"}), 400

        pesquisa = termo if termo.startswith("http") else f"ytsearch1:{termo}"
        ydl_opts = {'quiet': True, 'skip_download': True, 'default_search': 'ytsearch'}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(pesquisa, download=False)
                if 'entries' in info:
                    entries = info.get('entries', [])
                    if not entries: return jsonify({"erro": "Nenhum resultado encontrado."}), 404
                    info = entries[0]
                
                titulo = info.get('title', 'Sem Título')
                thumbnail = info.get('thumbnail', 'https://files.catbox.moe/0aa6f2.png')
                
            return jsonify({"title": titulo, "thumbnail": thumbnail})
        except Exception as e:
            return jsonify({"erro": "Erro ao buscar preview: " + str(e)}), 500

    @app.route('/api/adm/baixar-audio', methods=['POST'])
    def adm_baixar_audio():
        data = request.json or {}
        usuario_id, termo = data.get("usuario_id"), data.get("termo", "").strip()
        if not usuario_id: return jsonify({"erro": "ID obrigatório"}), 400
        
        permitido, tipo_ou_msg = checar_permissao(usuario_id)
        if not permitido: return jsonify({"erro": tipo_ou_msg}), 403
        if not termo: return jsonify({"erro": "Termo vazio"}), 400

        pesquisa = termo if termo.startswith("http") else f"ytsearch1:{termo}"
        out_dir = "downloads_temp"
        os.makedirs(out_dir, exist_ok=True)
        fid = str(uuid.uuid4())
        
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(out_dir, f"{fid}.%(ext)s"),
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
                'quiet': True,
                'default_search': 'ytsearch'
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(pesquisa, download=True)
                if 'entries' in info:
                    entries = info.get('entries', [])
                    if not entries: return jsonify({"erro": "Nenhum resultado encontrado."}), 404
                    info = entries[0]
                titulo = info.get('title', 'audio')
                
            path = os.path.join(out_dir, f"{fid}.mp3")
            if not os.path.exists(path): return jsonify({"erro": "Falha ao gerar MP3."}), 500

            registrar_sucesso_download(usuario_id, tipo_ou_msg)
            return send_file(path, as_attachment=True, download_name=f"{titulo[:50]}.mp3")
        except Exception as e:
            return jsonify({"erro": "Erro ao processar áudio: " + str(e)}), 500

    @app.route('/api/adm/baixar-video', methods=['POST'])
    def adm_baixar_video():
        data = request.json or {}
        usuario_id, termo = data.get("usuario_id"), data.get("termo", "").strip()
        if not usuario_id: return jsonify({"erro": "ID obrigatório"}), 400
        
        permitido, tipo_ou_msg = checar_permissao(usuario_id)
        if not permitido: return jsonify({"erro": tipo_ou_msg}), 403
        if not termo: return jsonify({"erro": "Termo vazio"}), 400

        pesquisa = termo if termo.startswith("http") else f"ytsearch1:{termo}"
        out_dir = "downloads_temp"
        os.makedirs(out_dir, exist_ok=True)
        fid = str(uuid.uuid4())
        
        try:
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': os.path.join(out_dir, f"{fid}.%(ext)s"),
                'quiet': True,
                'default_search': 'ytsearch'
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(pesquisa, download=True)
                if 'entries' in info:
                    entries = info.get('entries', [])
                    if not entries: return jsonify({"erro": "Nenhum resultado encontrado."}), 404
                    info = entries[0]
                titulo, ext = info.get('title', 'video'), info.get('ext', 'mp4')
                
            path = os.path.join(out_dir, f"{fid}.{ext}")
            if not os.path.exists(path): return jsonify({"erro": "Falha ao gerar MP4."}), 500

            registrar_sucesso_download(usuario_id, tipo_ou_msg)
            return send_file(path, as_attachment=True, download_name=f"{titulo[:50]}.{ext}")
        except Exception as e:
            return jsonify({"erro": "Erro ao processar vídeo: " + str(e)}), 500
