import datetime
import json
import math
import os
from datetime import date, datetime, time as dtime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf

# =========================================================================
# CONFIGURAÇÃO DA API E CREDENCIAIS
# =========================================================================
FINNHUB_API_KEY = "d9vr5m9r01qgk75po3m0d9vr5m9r01qgk75po3mg"
FINNHUB_SECRET = "d9vr5m9r01qgk75po3ng"


def get_finnhub_quote(symbol="EWZ"):
  url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
  try:
    response = requests.get(url, timeout=5)
    if response.status_code == 200:
      data = response.json()
      o_val = data.get("o")
      c_val = data.get("c")
      pc_val = data.get("pc")
      t_val = data.get("t")

      o = float(o_val) if o_val is not None else 0.0
      c = float(c_val) if c_val is not None else 0.0
      pc = float(pc_val) if pc_val is not None else 0.0
      t = int(t_val) if t_val is not None else 0

      return o, c, pc, t
  except Exception:
    pass
  return 0.0, 0.0, 0.0, 0


# =========================================================================
# FUNÇÕES DE FORMATAÇÃO
# =========================================================================
def fmt_br(val, decimals=2, prefix="", suffix=""):
  if val is None or pd.isna(val) or not isinstance(val, (int, float)):
    return "-"
  fmt_str = f"{{:,.{decimals}f}}"
  formatted = fmt_str.format(val)
  formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
  return f"{prefix}{formatted}{suffix}"


def fmt_pct(val):
  if val is None or pd.isna(val) or not isinstance(val, (int, float)):
    return "-"
  formatted = f"{val:+,.2f}%"
  return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


# =========================================================================
# CONFIGURAÇÃO DA PÁGINA WEB & INJEÇÃO DE CSS
# =========================================================================
st.set_page_config(
    page_title="Painel Mercado Futuro — B3 & CME & ADRs",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 2rem !important;
            padding-bottom: 2rem !important;
        }
        [data-testid="stVerticalBlock"] {
            gap: 0.3rem !important;
        }
        div[data-testid="stRadio"] {
            margin-top: 0px !important;
            margin-bottom: -5px !important;
            padding: 0px !important;
        }
        h1, h2, h3 {
            margin-top: 1.5rem !important;
            margin-bottom: 0.5rem !important;
            padding-top: 0px !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================================
# BANCO DE DADOS/PERSISTÊNCIA PROTEGIDA EM SESSION STATE & DISCO
# =========================================================================
CONFIG_FILE = "dados_salvos.json"

VALORES_PADRAO = {
    "ind_close": 130000.0,
    "ibov_close": 130000.0,
    "ewz_open_manual": 0.0,
    "ewz_close_manual": 0.0,
    "horario_abertura_eua": "10:30",
    "dias_uteis": 20,
    "tipo_variacao_alvos": "Tempo Real (Fech. Ant.)",
    "taxa_selic": 14.00,
    "vix_val": 18.0,
    "vix_fator": 1.25,
    "cdi_input": 10.50,
    "cupom_input": 4.50,
    "qtd_alvos_up": 4,
    "qtd_alvos_down": 4,
    "suporte_manual": 0.0,
    "resistencia_manual": 0.0,
}


def carregar_dados_disco():
  if os.path.exists(CONFIG_FILE):
    try:
      with open(CONFIG_FILE, "r") as f:
        dados = json.load(f)
        for k, v in VALORES_PADRAO.items():
          if k not in dados:
            dados[k] = v
        return dados
    except Exception:
      pass
  return VALORES_PADRAO.copy()


if "dados_persistes" not in st.session_state:
  st.session_state.dados_persistes = carregar_dados_disco()


def salvar_e_sincronizar(campo, chave_widget):
  """Callback executado ao alterar qualquer input na tela."""
  if chave_widget in st.session_state:
    st.session_state.dados_persistes[campo] = st.session_state[chave_widget]
    try:
      with open(CONFIG_FILE, "w") as f:
        json.dump(st.session_state.dados_persistes, f)
    except Exception as e:
      st.error(f"Erro ao salvar configurações: {e}")


def get_val(campo):
  return st.session_state.dados_persistes.get(campo, VALORES_PADRAO.get(campo))


# =========================================================================
# CONTROLE DE NAVEGAÇÃO E REFRESH DINÂMICO POR ABA
# =========================================================================
st.markdown(
    """
    <h1 style='font-size: 26px; margin: 0px 0px 5px 0px; padding: 0;'>
        Painel Mercado Futuro — B3 & CME & ADRs
    </h1>
    """,
    unsafe_allow_html=True,
)

aba_ativa = st.radio(
    "Navegação",
    ["Índice / EWZ", "Dólar", "ADRs EUA", "Futuros EUA", "Oração"],
    horizontal=True,
    label_visibility="collapsed",
)

if aba_ativa == "Índice / EWZ":
  refresh_interval = 5000
elif aba_ativa == "Dólar":
  refresh_interval = 5000
elif aba_ativa == "Oração":
  refresh_interval = 999999
else:
  refresh_interval = 30000

if aba_ativa != "Oração":
  st_autorefresh(interval=refresh_interval, key=f"autorefresh_{aba_ativa}")
  st.markdown(
      f"""
      <p style="margin-top: -6px; margin-bottom: 8px; font-size: 0.8rem; color: #808495;">
          ⏱️ Atualização automática para <b>{aba_ativa}</b>: a cada <b>{refresh_interval // 1000}s</b>
      </p>
      """,
      unsafe_allow_html=True,
  )


# =========================================================================
# REGRA DE NEGÓCIO E MÉTODOS AUXILIARES
# =========================================================================
@st.cache_data(ttl=3600)
def fetch_selic_meta_bcb():
  try:
    url = (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
    )
    response = requests.get(url, timeout=5)
    if response.status_code == 200:
      data = response.json()
      if data and len(data) > 0:
        return float(data[0]["valor"])
  except Exception:
    pass
  return 14.00


def calcular_dias_uteis_vencimento():
  hoje = date.today()
  ano = hoje.year
  mes = hoje.month

  if mes % 2 != 0:
    mes_venc = mes + 1
  else:
    mes_venc = mes

  def obter_quarta_vencimento(a, m):
    for dia in range(12, 19):
      d = date(a, m, dia)
      if d.weekday() == 2:
        return d
    return date(a, m, 15)

  vencimento = obter_quarta_vencimento(ano, mes_venc)

  if hoje >= vencimento:
    mes_venc += 2
    if mes_venc > 12:
      mes_venc = 2
      ano += 1
    vencimento = obter_quarta_vencimento(ano, mes_venc)

  dias_uteis = 0
  curr = hoje
  while curr < vencimento:
    if curr.weekday() < 5:
      dias_uteis += 1
    curr += timedelta(days=1)

  return max(dias_uteis, 1)


def calcular_du_dc_dolar():
  hoje = date.today()

  if hoje.month == 12:
    proximo_mes = date(hoje.year + 1, 1, 1)
  else:
    proximo_mes = date(hoje.year, hoje.month + 1, 1)

  vencimento = proximo_mes
  while vencimento.weekday() >= 5:
    vencimento += timedelta(days=1)

  dc = (vencimento - hoje).days

  du = 0
  curr = hoje
  while curr < vencimento:
    if curr.weekday() < 5:
      du += 1
    curr += timedelta(days=1)

  return max(du, 1), max(dc, 1)


def calcular_vwap(df):
  if df.empty or "Volume" not in df.columns:
    return df

  df["Typical_Price"] = (df["High"] + df["Low"] + df["Close"]) / 3.0
  df["TP_Vol"] = df["Typical_Price"] * df["Volume"]

  df["Cum_Vol"] = df["Volume"].cumsum()
  df["Cum_TP_Vol"] = df["TP_Vol"].cumsum()

  df["VWAP"] = df["Cum_TP_Vol"] / df["Cum_Vol"]
  return df


@st.cache_data(ttl=4)
def fetch_single_asset_data(ticker_symbol):
  try:
    ticker = yf.Ticker(ticker_symbol)
    daily_hist = ticker.history(period="5d", interval="1d")
    if len(daily_hist) < 2:
      return 0.0, 0.0, "Erro no histórico", "NEUTRO", "", 0.0, 0.0, 0.0

    prev_close = float(daily_hist["Close"].iloc[-2])
    open_price_day = float(daily_hist["Open"].iloc[-1])

    open_gap_pct = 0.0
    if prev_close > 0:
      open_gap_pct = ((open_price_day - prev_close) / prev_close) * 100.0

    intraday_5m = ticker.history(period="1d", interval="5m", prepost=True)

    if intraday_5m.empty:
      return (
          0.0,
          0.0,
          "Erro Intraday",
          "NEUTRO",
          "",
          open_price_day,
          prev_close,
          open_gap_pct,
      )

    last_candle = intraday_5m.iloc[-1]
    current_price = float(last_candle["Close"])
    open_price_5m = float(last_candle["Open"])

    now_bsb = datetime.now()
    time_now = now_bsb.time()

    hora_inicio_regular = dtime(10, 30)
    hora_fim_regular = dtime(18, 30)

    is_mercado_aberto = hora_inicio_regular <= time_now < hora_fim_regular

    if is_mercado_aberto:
      session_name = "Mercado Aberto (10:30 às 18:30 BSB)"
      base_close = prev_close
      direction = "COMPRANDO" if current_price >= open_price_5m else "VENDENDO"
      source = "(5m)"
    else:
      session_name = "Mercado Fechado / Pré-Market"
      base_close = float(daily_hist["Close"].iloc[-1])

    if current_price > 0 and base_close > 0:
      pct_change = ((current_price - base_close) / base_close) * 100.0

      if not is_mercado_aberto:
        direction = "COMPRANDO" if pct_change >= 0 else "VENDENDO"
        source = "(Pré-Mkt)"

      return (
          float(current_price),
          float(pct_change),
          session_name,
          direction,
          source,
          open_price_day,
          prev_close,
          open_gap_pct,
      )

    return (
        0.0,
        0.0,
        "Indisponível",
        "NEUTRO",
        "",
        open_price_day,
        prev_close,
        open_gap_pct,
    )
  except Exception as e:
    return 0.0, 0.0, f"Erro: {e}", "NEUTRO", "", 0.0, 0.0, 0.0


@st.cache_data(ttl=4)
def fetch_ewz_intraday_df():
  try:
    ticker = yf.Ticker("EWZ")
    df = ticker.history(period="1d", interval="5m", prepost=True)
    return df
  except Exception:
    return pd.DataFrame()


@st.cache_data(ttl=4)
def fetch_ibov_last_close():
  try:
    ticker = yf.Ticker("^BVSP")
    hist = ticker.history(period="5d", interval="1d")
    if not hist.empty and len(hist) >= 2:
      close_val = float(hist["Close"].iloc[-2])
      latest_date = hist.index[-1].date()
      if latest_date < pd.Timestamp.now().date():
        close_val = float(hist["Close"].iloc[-1])
      return close_val
  except Exception:
    pass
  return 130000.0


@st.cache_data(ttl=4)
def fetch_vix_previous_close():
  try:
    ticker = yf.Ticker("^VIX")
    hist = ticker.history(period="5d", interval="1d")
    if not hist.empty and len(hist) >= 2:
      close_val = float(hist["Close"].iloc[-2])
      latest_date = hist.index[-1].date()
      if latest_date < pd.Timestamp.now().date():
        close_val = float(hist["Close"].iloc[-1])
      return round(close_val, 2)
  except Exception:
    pass
  return 18.0


@st.cache_data(ttl=4)
def fetch_dolar_data():
  try:
    ticker = yf.Ticker("6L=F")
    hist = ticker.history(period="1d")
    if not hist.empty:
      last_row = hist.iloc[-1]
      close_p = float(last_row["Close"])
      high_p = float(last_row["High"])
      low_p = float(last_row["Low"])

      cme_inv = (1.0 / close_p) * 1000.0 if close_p > 0 else 0.0
      high_inv = (1.0 / low_p) * 1000.0 if low_p > 0 else 0.0
      low_inv = (1.0 / high_p) * 1000.0 if high_p > 0 else 0.0
      return cme_inv, high_inv, low_inv
  except Exception:
    pass
  return 0.0, 0.0, 0.0


@st.cache_data(ttl=5)
def buscar_dados_mercado_auto():
  tickers = {
      "spot": "BRL=X",
      "dxy": "DX-Y.NYB",
      "mxn": "USDMXN=X",
      "aud": "USDAUD=X",
  }

  dados = {}
  for chave, ticker_str in tickers.items():
    try:
      t = yf.Ticker(ticker_str)
      hist = t.history(period="5d", interval="1d")

      if len(hist) >= 2:
        prev_close = float(hist["Close"].iloc[-2])
        current_price = float(hist["Close"].iloc[-1])
        var_pct = ((current_price - prev_close) / prev_close) * 100.0

        dados[chave] = {
            "preco": current_price,
            "fech_ant": prev_close,
            "var_pct": var_pct,
        }
      else:
        dados[chave] = {"preco": 0.0, "fech_ant": 0.0, "var_pct": 0.0}
    except Exception:
      dados[chave] = {"preco": 0.0, "fech_ant": 0.0, "var_pct": 0.0}

  return dados


def calcular_dolar_teorico(spot, cdi_aa, cupom_aa, du, dc):
  try:
    base_di = max(float(1.0 + (cdi_aa / 100.0)), 0.0001)
    fator_di = base_di ** (float(max(du, 0)) / 252.0)

    base_cupom = max(float(1.0 + (cupom_aa / 100.0)), 0.0001)
    fator_cupom = base_cupom ** (float(max(dc, 0)) / 360.0)

    if isinstance(fator_di, complex):
      fator_di = float(fator_di.real)
    if isinstance(fator_cupom, complex) or fator_cupom == 0:
      fator_cupom = (
          float(fator_cupom.real)
          if isinstance(fator_cupom, complex)
          else 1.0001
      )
      if fator_cupom == 0:
        fator_cupom = 1.0001

    carrego_fator = float(fator_di) / float(fator_cupom)
    dolar_futuro = float(spot) * carrego_fator
    pontos_carrego = (carrego_fator - 1.0) * float(spot)

    return dolar_futuro, carrego_fator, pontos_carrego
  except Exception:
    return float(spot), 1.0, 0.0


@st.cache_data(ttl=30)
def fetch_dolar_teorico_intraday(cdi_aa, cupom_aa, du, dc):
  try:
    ticker = yf.Ticker("BRL=X")
    df = ticker.history(period="1d", interval="2m")

    if df.empty:
      return pd.DataFrame()

    base_di = max(float(1.0 + (cdi_aa / 100.0)), 0.0001)
    fator_di = base_di ** (float(max(du, 0)) / 252.0)

    base_cupom = max(float(1.0 + (cupom_aa / 100.0)), 0.0001)
    fator_cupom = base_cupom ** (float(max(dc, 0)) / 360.0)

    if isinstance(fator_di, complex):
      fator_di = float(fator_di.real)
    if isinstance(fator_cupom, complex) or fator_cupom == 0:
      fator_cupom = (
          float(fator_cupom.real)
          if isinstance(fator_cupom, complex)
          else 1.0001
      )
      if fator_cupom == 0:
        fator_cupom = 1.0001

    carrego_fator = float(fator_di) / float(fator_cupom)

    df["Futuro_Teorico"] = df["Close"] * carrego_fator * 1000.0
    df["Spot_Close"] = df["Close"] * 1000.0

    if df.index.tz is not None:
      df.index = df.index.tz_convert("America/Sao_Paulo")
    else:
      df.index = df.index.tz_localize("UTC").tz_convert("America/Sao_Paulo")

    df = df.between_time("09:00", "18:30")
    return df
  except Exception:
    return pd.DataFrame()


def color_variation(val):
  if isinstance(val, (int, float)):
    if val > 0:
      return "color: #00FF66; font-weight: bold;"
    elif val < 0:
      return "color: #FF4D4D; font-weight: bold;"
  return ""


def color_direction(val):
  if isinstance(val, str):
    if "COMPRANDO" in val:
      return "color: #00FF66; font-weight: bold;"
    elif "VENDENDO" in val:
      return "color: #FF4D4D; font-weight: bold;"
  return ""


# =========================================================================
# ABA 1: ÍNDICE / EWZ
# =========================================================================
if aba_ativa == "Índice / EWZ":
  col_tit1, col_tit2 = st.columns([0.7, 0.3])

  with col_tit1:
    st.subheader("🌐 Cotação EWZ")

  with col_tit2:
    opcoes_horario = ["10:30", "11:30"]
    idx_horario = (
        opcoes_horario.index(get_val("horario_abertura_eua"))
        if get_val("horario_abertura_eua") in opcoes_horario
        else 0
    )
    st.selectbox(
        "Abertura EUA:",
        opcoes_horario,
        index=idx_horario,
        key="w_horario_abertura_eua",
        on_change=salvar_e_sincronizar,
        args=("horario_abertura_eua", "w_horario_abertura_eua"),
    )

  (
      ewz_price,
      ewz_pct,
      ewz_state,
      ewz_direction,
      ewz_source,
      ewz_open_api,
      ewz_prev_close,
      _,
  ) = fetch_single_asset_data("EWZ")

  default_ibov = fetch_ibov_last_close()
  default_vix = fetch_vix_previous_close()
  default_du = calcular_dias_uteis_vencimento()
  selic_pesquisada = fetch_selic_meta_bcb()

  hora_str, min_str = get_val("horario_abertura_eua").split(":")
  horario_gatilho_inicio = dtime(int(hora_str), int(min_str) + 15, 0)
  horario_gatilho_fim = dtime(18, 30, 0)

  agora_dt = datetime.now()
  agora_time = agora_dt.time()
  is_dia_util = agora_dt.weekday() < 5

  if get_val("ewz_open_manual") == 0.0 and ewz_open_api > 0:
    st.session_state.dados_persistes["ewz_open_manual"] = ewz_open_api

  if (
      is_dia_util
      and (horario_gatilho_inicio <= agora_time <= horario_gatilho_fim)
      and ewz_open_api > 0
  ):
    st.session_state.dados_persistes["ewz_open_manual"] = ewz_open_api

  ewz_open = float(get_val("ewz_open_manual"))

  ewz_from_open_pct = 0.0
  if ewz_open > 0 and ewz_price > 0:
    ewz_from_open_pct = ((ewz_price - ewz_open) / ewz_open) * 100.0

  ewz_close_val = float(get_val("ewz_close_manual"))
  ewz_total_var_pct = 0.0
  if ewz_prev_close > 0 and ewz_close_val > 0:
    ewz_total_var_pct = (
        (ewz_close_val - ewz_prev_close) / ewz_prev_close
    ) * 100.0

  st.markdown(f"**Sessão:** {ewz_state}")

  color_var = "#00FF66" if ewz_pct >= 0 else "#FF4D4D"
  color_open_var = "#00FF66" if ewz_from_open_pct >= 0 else "#FF4D4D"
  color_total_var = "#00FF66" if ewz_total_var_pct >= 0 else "#FF4D4D"

  # =========================================================================
  # QUADROS PRINCIPAIS: 3 COLUNAS (TEMPO REAL, ABERTURA, FECHAMENTO ANTERIOR)
  # =========================================================================
  c1, c2, c3 = st.columns([330, 220, 220])

  with c1:
    color_dir_badge = (
        "#00FF66" if "COMPRANDO" in ewz_direction else "#FF4D4D"
    )

    st.markdown(
        f"""
            <div style="padding: 10px 12px; border-radius: 8px; border: 1px solid #333; background-color: rgba(255, 255, 255, 0.02);">
                <span style="font-size: 13px; color: #888;">Variação EWZ (Tempo Real)</span><br>
                <span style="font-size: 22px; font-weight: bold; color: #E0E0E0;">
                    {fmt_br(ewz_price, 2, "$")}
                </span>
                <span style="font-size: 16px; font-weight: bold; color: {color_var}; margin-left: 6px;">
                    {fmt_pct(ewz_pct)}
                </span>
                <div style="margin-top: 6px; font-size: 12px; font-weight: bold; color: {color_dir_badge};">
                    {ewz_direction} {ewz_source}
                </div>
                <hr style="margin: 8px 0; border: 0; border-top: 1px solid #333;">
                <span style="font-size: 12px; color: #aaa;">Var. pós-abertura:</span>
                <span style="font-size: 14px; font-weight: bold; color: {color_open_var}; margin-left: 6px;">
                    {fmt_pct(ewz_from_open_pct)}
                </span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with c2:
    fh_open, fh_current, fh_prev_close, _ = get_finnhub_quote("EWZ")

    fech_ant_efetivo = (
        fh_prev_close
        if fh_prev_close is not None and fh_prev_close > 0
        else ewz_prev_close
    )

    ewz_gap = 0.0
    if fech_ant_efetivo > 0 and ewz_open > 0:
      ewz_gap = ((ewz_open - fech_ant_efetivo) / fech_ant_efetivo) * 100.0

    color_gap = "#00FF66" if ewz_gap >= 0 else "#FF4D4D"

    fh_text = (
        f"US$ {fh_open:.2f}"
        if fh_open is not None and fh_open > 0
        else "Buscando dados..."
    )

    st.markdown(
        f"""
            <div style="padding: 10px 12px; border-radius: 8px; border: 1px solid #333; background-color: rgba(255, 255, 255, 0.02);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 13px; color: #888;">Abertura EWZ</span>
                    <span style="font-size: 10px; color: #29B6F6; font-weight: bold;">⚡ API: {fh_text}</span>
                </div>
            </div>
            """,
        unsafe_allow_html=True,
    )

    st.number_input(
        "Cotação Abertura Manual ($):",
        value=float(get_val("ewz_open_manual")),
        step=0.01,
        format="%.2f",
        key="w_ewz_open_manual",
        on_change=salvar_e_sincronizar,
        args=("ewz_open_manual", "w_ewz_open_manual"),
        label_visibility="collapsed",
    )

    st.markdown(
        f"""
            <div style="padding: 4px 12px; border-radius: 8px; border: 1px solid #222; background-color: rgba(255, 255, 255, 0.01); margin-top: 4px;">
                <span style="font-size: 12px; font-weight: bold; color: {color_gap};">
                    Gap: {fmt_pct(ewz_gap)} (Fech. Ant.: {fmt_br(fech_ant_efetivo, 2, "$")})
                </span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with c3:
    fech_ant_api_val = (
        fh_prev_close
        if fh_prev_close is not None and fh_prev_close > 0
        else ewz_prev_close
    )

    fh_prev_close_text = (
        f"US$ {fech_ant_api_val:.2f}"
        if fh_prev_close is not None and fh_prev_close > 0
        else "Buscando dados..."
    )

    st.markdown(
        f"""
            <div style="padding: 10px 12px; border-radius: 8px; border: 1px solid #333; background-color: rgba(255, 255, 255, 0.02);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 13px; color: #888;">Fechamento EWZ</span>
                    <span style="font-size: 10px; color: #AB47BC; font-weight: bold;">⚡ API: {fh_prev_close_text}</span>
                </div>
            </div>
            """,
        unsafe_allow_html=True,
    )

    st.number_input(
        "Cotação Fechamento Pregão Anterior Manual ($):",
        value=float(get_val("ewz_close_manual")),
        step=0.01,
        format="%.2f",
        key="w_ewz_close_manual",
        on_change=salvar_e_sincronizar,
        args=("ewz_close_manual", "w_ewz_close_manual"),
        label_visibility="collapsed",
    )

    st.markdown(
        f"""
            <div style="padding: 4px 12px; border-radius: 8px; border: 1px solid #222; background-color: rgba(255, 255, 255, 0.01); margin-top: 4px;">
                <span style="font-size: 12px; font-weight: bold; color: {color_total_var};">
                    Var. Total: {fmt_pct(ewz_total_var_pct)}
                </span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  ind_close = float(get_val("ind_close"))
  ibov_close = float(get_val("ibov_close"))
  taxa_selic = float(get_val("taxa_selic"))
  dias_uteis = int(get_val("dias_uteis"))
  vix_val = float(get_val("vix_val"))
  vix_fator = float(get_val("vix_fator"))

  st.markdown("---")
  col_proj_hdr, col_proj_opt = st.columns([0.45, 0.55])

  with col_proj_hdr:
    st.subheader("📊 INDFUT Projetado (Puro vs. EWZ + Dólar)")

  with col_proj_opt:
    opcoes_alvos = ["Tempo Real (Fech. Ant.)", "Pós-Abertura (Abertura EWZ)"]
    idx_tipo_alvos = (
        opcoes_alvos.index(get_val("tipo_variacao_alvos"))
        if get_val("tipo_variacao_alvos") in opcoes_alvos
        else 0
    )
    st.radio(
        "Usar no cálculo dos Alvos:",
        opcoes_alvos,
        index=idx_tipo_alvos,
        horizontal=True,
        key="w_tipo_variacao_alvos",
        on_change=salvar_e_sincronizar,
        args=("tipo_variacao_alvos", "w_tipo_variacao_alvos"),
    )

  var_usada = (
      ewz_from_open_pct
      if get_val("tipo_variacao_alvos") == "Pós-Abertura (Abertura EWZ)"
      else ewz_pct
  )
  label_var_usada = (
      f"Var. Pós-Abertura ({fmt_pct(ewz_from_open_pct)})"
      if get_val("tipo_variacao_alvos") == "Pós-Abertura (Abertura EWZ)"
      else f"Var. Tempo Real ({fmt_pct(ewz_pct)})"
  )

  # -------------------------------------------------------------------------
  # CÁLCULOS DAS DUAS PRECIFICAÇÕES
  # -------------------------------------------------------------------------
  if ind_close > 0:
    var_puro_abs = abs(var_usada) / 100.0
    alvo_alta_puro = ind_close * (1 + var_puro_abs)
    alvo_baixa_puro = ind_close * (1 - var_puro_abs)
  else:
    alvo_alta_puro, alvo_baixa_puro = 0.0, 0.0

  mkt_auto_dolar = buscar_dados_mercado_auto()
  var_dolar_pct = mkt_auto_dolar["spot"]["var_pct"]
  var_combinada_pct = var_usada - (0.5 * var_dolar_pct)

  if ind_close > 0:
    var_comb_abs = abs(var_combinada_pct) / 100.0
    alvo_alta_dol = ind_close * (1 + var_comb_abs)
    alvo_baixa_dol = ind_close * (1 - var_comb_abs)
  else:
    alvo_alta_dol, alvo_baixa_dol = 0.0, 0.0

  if "ultimo_alvo_alta" not in st.session_state:
    st.session_state.ultimo_alvo_alta = 0.0
  if "ultimo_alvo_baixa" not in st.session_state:
    st.session_state.ultimo_alvo_baixa = 0.0

  if st.session_state.ultimo_alvo_alta != 0:
    diff_alvo_alta = alvo_alta_dol - st.session_state.ultimo_alvo_alta
    diff_alvo_baixa = alvo_baixa_dol - st.session_state.ultimo_alvo_baixa

    if var_combinada_pct > 0 and abs(diff_alvo_alta) >= 300:
      st.error(
          f"🚨 **ALARME DE ALTA!** Variação do alvo: **+{fmt_br(diff_alvo_alta, 0)} pontos**!",
          icon="🚨",
      )
      st.toast(
          f"⚡ ALVO DE ALTA: +{fmt_br(diff_alvo_alta, 0)} pts!", icon="📈"
      )

    elif var_combinada_pct < 0 and abs(diff_alvo_baixa) >= 300:
      st.error(
          f"🚨 **ALARME DE BAIXA!** Variação do alvo: **{fmt_br(diff_alvo_baixa, 0)} pontos**!",
          icon="🚨",
      )
      st.toast(
          f"⚡ ALVO DE BAIXA: {fmt_br(diff_alvo_baixa, 0)} pts!", icon="📉"
      )

  st.session_state.ultimo_alvo_alta = alvo_alta_dol
  st.session_state.ultimo_alvo_baixa = alvo_baixa_dol

  taxa_diaria = (taxa_selic / 100.0) * (dias_uteis / 252.0)
  preco_justo = ibov_close * (1 + taxa_diaria)

  if ind_close > 0 and vix_val > 0:
    sigma_diaria = (vix_val / 100.0) / math.sqrt(252)
    pontos_totais = sigma_diaria * vix_fator * ind_close
    vix_teto = ind_close + (pontos_totais / 2.0)
    vix_piso = ind_close - (pontos_totais / 2.0)
  else:
    vix_teto, vix_piso = 0.0, 0.0

  r1, r2 = st.columns(2)
  is_comprando = var_usada >= 0
  is_vendendo = var_usada < 0

  style_alta = (
      "border: 2px solid #00FF66; background-color: rgba(0, 255, 102, 0.05);"
      if is_comprando
      else "border: 1px solid #333;"
  )
  style_baixa = (
      "border: 2px solid #FF4D4D; background-color: rgba(255, 77, 77, 0.05);"
      if is_vendendo
      else "border: 1px solid #333;"
  )

  with r1:
    st.markdown(
        f"""
            <div style="padding: 12px; border-radius: 8px; margin-bottom: 15px; {style_alta}">
                <span style="font-size: 13px; color: #888;">▲ ALVO DE ALTA ({label_var_usada})</span><br>
                <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 4px;">
                    <div>
                        <span style="font-size: 11px; color: #AAA;">Tradicional (Puro EWZ)</span><br>
                        <span style="font-size: 22px; font-weight: bold; color: {'#00FF66' if is_comprando else 'inherit'};">
                            {fmt_br(alvo_alta_puro, 0)} pts
                        </span>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 11px; color: #29B6F6;">Com Dólar (USD: {fmt_pct(var_dolar_pct)})</span><br>
                        <span style="font-size: 22px; font-weight: bold; color: #29B6F6;">
                            {fmt_br(alvo_alta_dol, 0)} pts
                        </span>
                    </div>
                </div>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with r2:
    st.markdown(
        f"""
            <div style="padding: 12px; border-radius: 8px; {style_baixa}">
                <span style="font-size: 13px; color: #888;">▼ ALVO DE BAIXA ({label_var_usada})</span><br>
                <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 4px;">
                    <div>
                        <span style="font-size: 11px; color: #AAA;">Tradicional (Puro EWZ)</span><br>
                        <span style="font-size: 22px; font-weight: bold; color: {'#FF4D4D' if is_vendendo else 'inherit'};">
                            {fmt_br(alvo_baixa_puro, 0)} pts
                        </span>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 11px; color: #29B6F6;">Com Dólar (USD: {fmt_pct(var_dolar_pct)})</span><br>
                        <span style="font-size: 22px; font-weight: bold; color: #29B6F6;">
                            {fmt_br(alvo_baixa_dol, 0)} pts
                        </span>
                    </div>
                </div>
            </div>
            """,
        unsafe_allow_html=True,
    )

  col_sup, col_res, col_qtd_up, col_qtd_down = st.columns(4)

  with col_sup:
    st.number_input(
        "Suporte ($):",
        value=float(get_val("suporte_manual")),
        step=0.01,
        format="%.2f",
        key="w_suporte_manual",
        on_change=salvar_e_sincronizar,
        args=("suporte_manual", "w_suporte_manual"),
    )

  with col_res:
    st.number_input(
        "Resistência ($):",
        value=float(get_val("resistencia_manual")),
        step=0.01,
        format="%.2f",
        key="w_resistencia_manual",
        on_change=salvar_e_sincronizar,
        args=("resistencia_manual", "w_resistencia_manual"),
    )

  with col_qtd_up:
    st.number_input(
        "Deltas trava ▲",
        min_value=1,
        max_value=15,
        value=int(get_val("qtd_alvos_up")),
        step=1,
        key="w_qtd_alvos_up",
        on_change=salvar_e_sincronizar,
        args=("qtd_alvos_up", "w_qtd_alvos_up"),
    )

  with col_qtd_down:
    st.number_input(
        "Deltas trava ▼",
        min_value=1,
        max_value=15,
        value=int(get_val("qtd_alvos_down")),
        step=1,
        key="w_qtd_alvos_down",
        on_change=salvar_e_sincronizar,
        args=("qtd_alvos_down", "w_qtd_alvos_down"),
    )

  suporte_val = float(get_val("suporte_manual"))
  resistencia_val = float(get_val("resistencia_manual"))
  qtd_alvos_up = int(get_val("qtd_alvos_up"))
  qtd_alvos_down = int(get_val("qtd_alvos_down"))

  st.sidebar.markdown("---")
  st.sidebar.subheader("⚙️ Filtros do Gráfico EWZ")
  plotar_trava = st.sidebar.checkbox("Mostrar Linha da Trava", value=True)
  plotar_abertura = st.sidebar.checkbox("Mostrar Linha de Abertura", value=True)
  plotar_fechamento = st.sidebar.checkbox(
      "Mostrar Linha de Fechamento", value=True
  )
  plotar_maxima = st.sidebar.checkbox("Mostrar Linha de Máxima", value=True)
  plotar_minima = st.sidebar.checkbox("Mostrar Linha de Mínima", value=True)

  st.subheader("📊 Gráfico EWZ")
  df_ewz_chart = fetch_ewz_intraday_df()

  if not df_ewz_chart.empty:
    df_ewz_chart = calcular_vwap(df_ewz_chart)
    df_ewz_chart["SMA20"] = df_ewz_chart["Close"].rolling(window=20).mean()

    maxima_dia = float(df_ewz_chart["High"].max())
    minima_dia = float(df_ewz_chart["Low"].min())
    preco_atual_candle = float(df_ewz_chart["Close"].iloc[-1])

    agora = datetime.now()
    minuto_atual = agora.minute
    segundo_atual = agora.second
    minuto_restante = 4 - (minuto_atual % 5)
    segundo_restante = 59 - segundo_atual
    timer_str = f"⏱️{minuto_restante:02d}:{segundo_restante:02d}"

    trava_val = 0.0
    if ewz_open > 0 and fech_ant_efetivo > 0:
      trava_val = (ewz_open + fech_ant_efetivo) / 2.0

    precos_referencia = [preco_atual_candle]
    if plotar_maxima:
      precos_referencia.append(maxima_dia)
    if plotar_minima:
      precos_referencia.append(minima_dia)
    if plotar_abertura and ewz_open > 0:
      precos_referencia.append(ewz_open)
    if plotar_fechamento and fech_ant_efetivo > 0:
      precos_referencia.append(fech_ant_efetivo)
    if suporte_val > 0:
      precos_referencia.append(suporte_val)
    if resistencia_val > 0:
      precos_referencia.append(resistencia_val)

    if plotar_trava and trava_val > 0:
      precos_referencia.append(trava_val)
      precos_referencia.append(
          trava_val * (1.0 + (qtd_alvos_up * 0.5 / 100.0))
      )
      precos_referencia.append(
          trava_val * (1.0 - (qtd_alvos_down * 0.5 / 100.0))
      )

    y_min_val = min(precos_referencia)
    y_max_val = max(precos_referencia)
    padding = (y_max_val - y_min_val) * 0.05 if y_max_val != y_min_val else 1.0

    y_min = y_min_val - padding
    y_max = y_max_val + padding

    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=df_ewz_chart.index,
            open=df_ewz_chart["Open"],
            high=df_ewz_chart["High"],
            low=df_ewz_chart["Low"],
            close=df_ewz_chart["Close"],
            name="EWZ 5m",
            increasing_line_color="#00FF66",
            decreasing_line_color="#FF4D4D",
        )
    )

    if "VWAP" in df_ewz_chart.columns:
      fig.add_trace(
          go.Scatter(
              x=df_ewz_chart.index,
              y=df_ewz_chart["VWAP"],
              mode="lines",
              name="VWAP Diária",
              line=dict(color="#FFB300", width=2.5),
          )
      )

    fig.add_trace(
        go.Scatter(
            x=df_ewz_chart.index,
            y=df_ewz_chart["SMA20"],
            mode="lines",
            name="Média (SMA 20)",
            line=dict(color="#29B6F6", width=1.5, dash="solid"),
        )
    )

    if plotar_maxima:
      var_max_pct = (
          ((maxima_dia - fech_ant_efetivo) / fech_ant_efetivo) * 100.0
          if fech_ant_efetivo > 0
          else 0.0
      )
      text_max = (
          f"Máxima: {fmt_br(maxima_dia, 2, '$')} ({fmt_pct(var_max_pct)})"
      )
      fig.add_hline(
          y=maxima_dia,
          line_dash="dot",
          line_color="#00E676",
          line_width=1.5,
          annotation_text=text_max,
          annotation_position="top right",
          annotation_font_color="#00E676",
      )

    if plotar_minima:
      var_min_pct = (
          ((minima_dia - fech_ant_efetivo) / fech_ant_efetivo) * 100.0
          if fech_ant_efetivo > 0
          else 0.0
      )
      text_min = (
          f"Mínima: {fmt_br(minima_dia, 2, '$')} ({fmt_pct(var_min_pct)})"
      )
      fig.add_hline(
          y=minima_dia,
          line_dash="dot",
          line_color="#FF5252",
          line_width=1.5,
          annotation_text=text_min,
          annotation_position="bottom right",
          annotation_font_color="#FF5252",
      )

    if suporte_val > 0:
      fig.add_hline(
          y=suporte_val,
          line_dash="solid",
          line_color="#00FF66",
          line_width=2.5,
          annotation_text=f"Suporte: {fmt_br(suporte_val, 2, '$')}",
          annotation_position="bottom left",
          annotation_font_color="#00FF66",
      )

    if resistencia_val > 0:
      fig.add_hline(
          y=resistencia_val,
          line_dash="solid",
          line_color="#FF4D4D",
          line_width=2.5,
          annotation_text=f"Resistência: {fmt_br(resistencia_val, 2, '$')}",
          annotation_position="top left",
          annotation_font_color="#FF4D4D",
      )

    fig.add_hline(
        y=preco_atual_candle,
        line_dash="dot",
        line_color="#FFEB3B",
        line_width=1,
        annotation_text=f"▶ {fmt_br(preco_atual_candle, 2, '$')} {timer_str}",
        annotation_position="right",
        annotation_font_color="#FFEB3B",
    )

    if plotar_abertura and ewz_open > 0:
      fig.add_hline(
          y=ewz_open,
          line_dash="solid",
          line_color="#FFFF00",
          line_width=1.5,
          annotation_text=f"Abertura: {fmt_br(ewz_open, 2, '$')}",
          annotation_position="top left",
          annotation_font_color="#FFFF00",
      )

    if plotar_fechamento and fech_ant_efetivo > 0:
      fig.add_hline(
          y=fech_ant_efetivo,
          line_dash="solid",
          line_color="#29B6F6",
          line_width=1,
          annotation_text=(
              f"Fechamento: {fmt_br(fech_ant_efetivo, 2, '$')}"
          ),
          annotation_position="top left",
          annotation_font_color="#29B6F6",
      )

    if plotar_trava and trava_val > 0:
      fig.add_hline(
          y=trava_val,
          line_dash="solid",
          line_color="#FFFFFF",
          line_width=2,
          annotation_text=f"TRAVA: {fmt_br(trava_val, 2, '$')}",
          annotation_position="top left",
          annotation_font_color="#FFFFFF",
      )

      for i in range(1, qtd_alvos_up + 1):
        pct_fator = i * 0.5
        alvo_up = trava_val * (1.0 + (pct_fator / 100.0))
        fig.add_hline(
            y=alvo_up,
            line_dash="dot",
            line_color="#CE93D8",
            line_width=1,
            annotation_text=f"+{pct_fator:.1f}%: {fmt_br(alvo_up, 2, '$')}",
            annotation_position="top left",
            annotation_font_color="#CE93D8",
        )

      for i in range(1, qtd_alvos_down + 1):
        pct_fator = i * 0.5
        alvo_down = trava_val * (1.0 - (pct_fator / 100.0))
        fig.add_hline(
            y=alvo_down,
            line_dash="dot",
            line_color="#CE93D8",
            line_width=1,
            annotation_text=f"-{pct_fator:.1f}%: {fmt_br(alvo_down, 2, '$')}",
            annotation_position="bottom left",
            annotation_font_color="#CE93D8",
        )

    fig.update_layout(
        template="plotly_dark",
        height=600,
        margin=dict(l=10, r=120, t=25, b=10),
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        hovermode="x unified",
        uirevision="EWZ_CHART_ZOOM",
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="#222634",
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikecolor="#FFFFFF",
            spikedash="dot",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#222634",
            title=f"Preço ($)  |  {timer_str}",
            autorange=False,
            range=[y_min, y_max],
            fixedrange=False,
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikecolor="#FFFFFF",
            spikedash="dot",
        ),
    )

    st.plotly_chart(fig, width="stretch")
  else:
    st.info("Aguardando carregamento de dados intraday do EWZ...")

  st.markdown(
      f"""
        <div style="padding: 12px 16px; border-radius: 10px; border: 1px solid #1E88E5; background-color: rgba(30, 136, 229, 0.1); margin-bottom: 20px; margin-top: 20px;">
            <span style="font-size: 14px; font-weight: 600; color: #90CAF9; letter-spacing: 0.5px;">★ PREÇO JUSTO TEÓRICO (IBOV + Carry)</span><br>
            <span style="font-size: 28px; font-weight: bold; color: #E3F2FD;">{fmt_br(preco_justo, 0)} pts</span>
        </div>
        """,
      unsafe_allow_html=True,
  )

  v1, v2 = st.columns(2)
  with v1:
    st.markdown(
        f"""
            <div style="padding: 12px; border-radius: 10px; border: 1px solid #00FF66; background-color: rgba(0, 255, 102, 0.05);">
                <span style="font-size: 13px; color: #888;">🛡 TETO VIX</span><br>
                <span style="font-size: 24px; font-weight: bold; color: #00FF66;">
                    {fmt_br(vix_teto, 0)} pts
                </span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with v2:
    st.markdown(
        f"""
            <div style="padding: 12px; border-radius: 10px; border: 1px solid #FF4D4D; background-color: rgba(255, 77, 77, 0.05);">
                <span style="font-size: 13px; color: #888;">⚓ PISO VIX</span><br>
                <span style="font-size: 24px; font-weight: bold; color: #FF4D4D;">
                    {fmt_br(vix_piso, 0)} pts
                </span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  st.divider()

  st.subheader("⚙️ Parâmetros do Modelo")

  col_in1, col_in2 = st.columns(2)
  with col_in1:
    st.number_input(
        "Última Atualização INDFUT (Pts)",
        value=float(get_val("ind_close")),
        step=100.0,
        key="w_ind_close",
        on_change=salvar_e_sincronizar,
        args=("ind_close", "w_ind_close"),
    )
    st.number_input(
        "Fech. IBOV",
        value=float(get_val("ibov_close")),
        step=100.0,
        key="w_ibov_close",
        on_change=salvar_e_sincronizar,
        args=("ibov_close", "w_ibov_close"),
    )
    st.number_input(
        "Selic %",
        value=float(get_val("taxa_selic")),
        step=0.25,
        format="%.2f",
        key="w_taxa_selic",
        on_change=salvar_e_sincronizar,
        args=("taxa_selic", "w_taxa_selic"),
    )

  with col_in2:
    st.number_input(
        "Dias Úteis (DU)",
        value=int(get_val("dias_uteis")),
        step=1,
        key="w_dias_uteis",
        on_change=salvar_e_sincronizar,
        args=("dias_uteis", "w_dias_uteis"),
    )
    st.number_input(
        "VIX",
        value=float(get_val("vix_val")),
        step=0.1,
        key="w_vix_val",
        on_change=salvar_e_sincronizar,
        args=("vix_val", "w_vix_val"),
    )
    st.number_input(
        "Fator VIX",
        value=float(get_val("vix_fator")),
        step=0.05,
        key="w_vix_fator",
        on_change=salvar_e_sincronizar,
        args=("vix_fator", "w_vix_fator"),
    )


# =========================================================================
# ABA 2: DÓLAR
# =========================================================================
elif aba_ativa == "Dólar":
  st.subheader("🌐 Cotações CME (6L=F)")
  cme, high, low = fetch_dolar_data()

  d1, d2, d3 = st.columns(3)

  with d1:
    st.markdown(
        f"""
            <div style="padding: 12px 16px; border-radius: 10px; border: 2px solid #1E88E5; background-color: rgba(30, 136, 229, 0.08);">
                <span style="font-size: 13px; font-weight: 600; color: #90CAF9;">CME (1 / Close)</span><br>
                <span style="font-size: 26px; font-weight: bold; color: #64B5F6;">{fmt_br(cme, 2)}</span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with d2:
    st.markdown(
        f"""
            <div style="padding: 12px 16px; border-radius: 10px; border: 2px solid #00E676; background-color: rgba(0, 230, 118, 0.08);">
                <span style="font-size: 13px; font-weight: 600; color: #B9F6CA;">CME HIGH (1 / Low)</span><br>
                <span style="font-size: 26px; font-weight: bold; color: #69F0AE;">{fmt_br(high, 2)}</span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with d3:
    st.markdown(
        f"""
            <div style="padding: 12px 16px; border-radius: 10px; border: 2px solid #FF5252; background-color: rgba(255, 82, 82, 0.08);">
                <span style="font-size: 13px; font-weight: 600; color: #FF8A80;">CME LOW (1 / High)</span><br>
                <span style="font-size: 26px; font-weight: bold; color: #FF5252;">{fmt_br(low, 2)}</span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  st.divider()

  st.subheader("⚡ Dólar Futuro & Justíssimo (Automatizado)")

  mkt = buscar_dados_mercado_auto()

  st.markdown("**🌐 Cotações Globais / Pré-Market**")
  c1, c2, c3, c4 = st.columns(4)

  spot_milhar = mkt["spot"]["preco"] * 1000.0

  c1.metric(
      "Dólar Spot (USD/BRL)",
      fmt_br(spot_milhar, 2),
      fmt_pct(mkt["spot"]["var_pct"]),
  )
  c2.metric(
      "DXY (Índice Dólar)",
      fmt_br(mkt["dxy"]["preco"], 2),
      fmt_pct(mkt["dxy"]["var_pct"]),
  )
  c3.metric(
      "USD/MXN (Peso Mex)",
      fmt_br(mkt["mxn"]["preco"], 4),
      fmt_pct(mkt["mxn"]["var_pct"]),
  )
  c4.metric(
      "USD/AUD (Dólar Aus)",
      fmt_br(mkt["aud"]["preco"], 4),
      fmt_pct(mkt["aud"]["var_pct"]),
  )

  st.divider()

  du_auto_dolar, dc_auto_dolar = calcular_du_dc_dolar()

  st.subheader("⚙️ Parâmetros da Curva de Juros")
  col_j1, col_j2, col_j3, col_j4 = st.columns(4)

  with col_j1:
    st.number_input(
        "Taxa DI (% a.a.)",
        value=float(get_val("cdi_input")),
        step=0.01,
        format="%.2f",
        key="w_cdi_input",
        on_change=salvar_e_sincronizar,
        args=("cdi_input", "w_cdi_input"),
    )
  with col_j2:
    st.number_input(
        "Cupom DDI (% a.a.)",
        value=float(get_val("cupom_input")),
        step=0.01,
        format="%.2f",
        key="w_cupom_input",
        on_change=salvar_e_sincronizar,
        args=("cupom_input", "w_cupom_input"),
    )
  with col_j3:
    st.number_input("Dias Úteis (DU)", value=du_auto_dolar, step=1)
  with col_j4:
    st.number_input("Dias Corridos (DC)", value=dc_auto_dolar, step=1)

  cdi_input = float(get_val("cdi_input"))
  cupom_input = float(get_val("cupom_input"))
  du_input = du_auto_dolar
  dc_input = dc_auto_dolar

  spot_atual = mkt["spot"]["preco"] if mkt["spot"]["preco"] > 0 else 5.0000
  futuro_teorico, fator_carrego, pts_carrego = calcular_dolar_teorico(
      spot_atual, cdi_input, cupom_input, du_input, dc_input
  )

  peso_dxy, peso_mxn, peso_aud = 0.40, 0.40, 0.20
  cesta_ext_pct = (
      (mkt["dxy"]["var_pct"] * peso_dxy)
      + (mkt["mxn"]["var_pct"] * peso_mxn)
      + (mkt["aud"]["var_pct"] * peso_aud)
  )

  spot_fech_ant = (
      mkt["spot"]["fech_ant"] if mkt["spot"]["fech_ant"] > 0 else spot_atual
  )
  spot_projetado = spot_fech_ant * (1.0 + (cesta_ext_pct / 100.0))

  futuro_justissimo, _, _ = calcular_dolar_teorico(
      spot_projetado, cdi_input, cupom_input, du_input, dc_input
  )

  futuro_teorico_milhar = futuro_teorico * 1000.0
  spot_projetado_milhar = spot_projetado * 1000.0
  futuro_justissimo_milhar = futuro_justissimo * 1000.0

  if "alarmes_dolar" not in st.session_state:
    st.session_state.alarmes_dolar = []

  if "ultimo_dolar_teorico" not in st.session_state:
    st.session_state.ultimo_dolar_teorico = futuro_teorico_milhar

  prev_dolar_teorico = st.session_state.ultimo_dolar_teorico
  diff_dolar = futuro_teorico_milhar - prev_dolar_teorico

  if abs(diff_dolar) >= 100.0 and prev_dolar_teorico > 0:
    tipo_alarme = "ALTA" if diff_dolar > 0 else "BAIXA"

    st.session_state.alarmes_dolar.append({
        "horario": pd.Timestamp.now(tz="America/Sao_Paulo"),
        "valor": futuro_teorico_milhar,
        "variacao": diff_dolar,
        "tipo": tipo_alarme,
    })

    if tipo_alarme == "ALTA":
      st.error(
          f"🚨 **ALARME DÓLAR (ALTA)!** Variação de **+{fmt_br(diff_dolar, 2)} pontos** no Dólar Teórico!",
          icon="🚨",
      )
      st.toast(f"⚡ DÓLAR ALTA: +{fmt_br(diff_dolar, 2)} pts!", icon="📈")
    else:
      st.error(
          f"🚨 **ALARME DÓLAR (BAIXA)!** Variação de **{fmt_br(diff_dolar, 2)} pontos** no Dólar Teórico!",
          icon="🚨",
      )
      st.toast(f"⚡ DÓLAR BAIXA: {fmt_br(diff_dolar, 2)} pts!", icon="📉")

  st.session_state.ultimo_dolar_teorico = futuro_teorico_milhar

  st.divider()

  st.subheader("📊 Resultados Automatizados")
  r1, r2, r3 = st.columns(3)

  with r1:
    st.markdown(
        f"""
            <div style="padding: 15px; border-radius: 10px; border: 1px solid #1E88E5; background-color: rgba(30, 136, 229, 0.1);">
                <span style="font-size: 13px; color: #90CAF9;">DÓLAR FUTURO TEÓRICO (Spot + Carrego)</span><br>
                <span style="font-size: 26px; font-weight: bold; color: #E3F2FD;">{fmt_br(futuro_teorico_milhar, 2)}</span><br>
                <span style="font-size: 12px; color: #888;">Carrego de Juros: {fmt_br(pts_carrego * 1000, 2, "+")} pts</span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with r2:
    st.markdown(
        f"""
            <div style="padding: 15px; border-radius: 10px; border: 1px solid #00E676; background-color: rgba(0, 230, 118, 0.1);">
                <span style="font-size: 13px; color: #B9F6CA;">SPOT PROJETADO NA ABERTURA</span><br>
                <span style="font-size: 26px; font-weight: bold; color: #E8F5E9;">{fmt_br(spot_projetado_milhar, 2)}</span><br>
                <span style="font-size: 12px; color: #888;">Cesta Internacional: {fmt_pct(cesta_ext_pct)}</span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  with r3:
    st.markdown(
        f"""
            <div style="padding: 15px; border-radius: 10px; border: 1px solid #FFD600; background-color: rgba(255, 214, 0, 0.1);">
                <span style="font-size: 13px; color: #FFE57F;">FUTURO JUSTÍSSIMO DE ABERTURA</span><br>
                <span style="font-size: 26px; font-weight: bold; color: #FFFDE7;">{fmt_br(futuro_justissimo_milhar, 2)}</span><br>
                <span style="font-size: 12px; color: #888;">Spot Projetado + Carrego DI</span>
            </div>
            """,
        unsafe_allow_html=True,
    )

  st.divider()
  st.subheader(
      "📈 Gráfico Intraday — Dólar Futuro Teórico (09:00 às 18:30) [Amostragem de"
      " 2 min]"
  )

  df_teorico = fetch_dolar_teorico_intraday(
      cdi_input, cupom_input, du_input, dc_input
  )

  if not df_teorico.empty:
    fig_dolar = go.Figure()

    fig_dolar.add_trace(
        go.Scatter(
            x=df_teorico.index,
            y=df_teorico["Futuro_Teorico"],
            mode="lines",
            name="Dólar Futuro Teórico (2m)",
            line=dict(color="#00E676", width=2),
        )
    )

    fig_dolar.add_trace(
        go.Scatter(
            x=df_teorico.index,
            y=df_teorico["Spot_Close"],
            mode="lines",
            name="Dólar Spot (USD/BRL)",
            line=dict(color="#29B6F6", width=1.5, dash="solid"),
        )
    )

    if st.session_state.alarmes_dolar:
      alarmes_alta_x = [
          a["horario"]
          for a in st.session_state.alarmes_dolar
          if a["tipo"] == "ALTA"
      ]
      alarmes_alta_y = [
          a["valor"] for a in st.session_state.alarmes_dolar if a["tipo"] == "ALTA"
      ]
      alarmes_alta_txt = [
          f"🚨 Alta +{fmt_br(a['variacao'], 2)} pts"
          for a in st.session_state.alarmes_dolar
          if a["tipo"] == "ALTA"
      ]

      alarmes_baixa_x = [
          a["horario"]
          for a in st.session_state.alarmes_dolar
          if a["tipo"] == "BAIXA"
      ]
      alarmes_baixa_y = [
          a["valor"]
          for a in st.session_state.alarmes_dolar
          if a["tipo"] == "BAIXA"
      ]
      alarmes_baixa_txt = [
          f"🚨 Baixa {fmt_br(a['variacao'], 2)} pts"
          for a in st.session_state.alarmes_dolar
          if a["tipo"] == "BAIXA"
      ]

      if alarmes_alta_x:
        fig_dolar.add_trace(
            go.Scatter(
                x=alarmes_alta_x,
                y=alarmes_alta_y,
                mode="markers+text",
                name="Alarme Alta (≥5pts)",
                marker=dict(symbol="triangle-up", size=14, color="#00FF66"),
                text=alarmes_alta_txt,
                textposition="top center",
                textfont=dict(color="#00FF66", size=11),
            )
        )

      if alarmes_baixa_x:
        fig_dolar.add_trace(
            go.Scatter(
                x=alarmes_baixa_x,
                y=alarmes_baixa_y,
                mode="markers+text",
                name="Alarme Baixa (≥5pts)",
                marker=dict(symbol="triangle-down", size=14, color="#FF4D4D"),
                text=alarmes_baixa_txt,
                textposition="bottom center",
                textfont=dict(color="#FF4D4D", size=11),
            )
        )

    fig_dolar.update_layout(
        template="plotly_dark",
        height=450,
        margin=dict(l=10, r=10, t=25, b=10),
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        hovermode="x unified",
        uirevision="DOLAR_CHART_ZOOM",
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="#222634",
            title="Horário (BSB)",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#222634",
            title="Preço (Milhar / Pts)",
            tickformat=".2f",
        ),
    )

    st.plotly_chart(fig_dolar, width="stretch")
  else:
    st.info("Aguardando dados intraday do Dólar Spot para montar o gráfico...")

  if st.button("🗑️ Apagar Alarmes do Gráfico", key="btn_apagar_alarmes_dolar"):
    st.session_state.alarmes_dolar = []
    st.success("Alarmes apagados com sucesso!")
    st.rerun()


# =========================================================================
# ABA 3: ADRs EUA
# =========================================================================
elif aba_ativa == "ADRs EUA":
  st.subheader("Monitoramento de ADRs Brasileiras")

  adr_tickers = [
      "PBR",
      "VALE",
      "ITUB",
      "BBD",
      "ABEV",
      "GGB",
      "EMBJ",
      "SBS",
      "NU",
      "STNE",
  ]
  records = []

  for ticker in adr_tickers:
    price, pct, state, direction, source, open_p, prev_c, gap = (
        fetch_single_asset_data(ticker)
    )
    records.append({
        "Ticker": ticker,
        "Fech. Ant. ($)": fmt_br(prev_c, 2, "$"),
        "Abertura ($)": fmt_br(open_p, 2, "$"),
        "Preço ($)": fmt_br(price, 2, "$"),
        "Var (%)": pct,
        "Gap (%)": gap,
        "Direção": f"{direction} {source}",
    })

  df_adrs = pd.DataFrame(records)

  styled_df_adrs = (
      df_adrs.style.map(color_variation, subset=["Var (%)", "Gap (%)"])
      .map(color_direction, subset=["Direção"])
      .format({"Var (%)": lambda v: fmt_pct(v), "Gap (%)": lambda v: fmt_pct(v)})
  )

  st.dataframe(styled_df_adrs, width="stretch", hide_index=True)


# =========================================================================
# ABA 4: FUTUROS EUA
# =========================================================================
elif aba_ativa == "Futuros EUA":
  st.subheader("Principais Contratos Futuros Americanos")

  futuros_map = {
      "ES=F": "S&P 500 Futuro",
      "NQ=F": "Nasdaq 100 Futuro",
      "YM=F": "Dow Jones Futuro",
      "RTY=F": "Russell 2000 Futuro",
      "CL=F": "Petróleo WTI",
      "GC=F": "Ouro Futuro",
  }

  records_futuros = []

  for ticker, nome in futuros_map.items():
    price, pct, state, direction, source, open_p, prev_c, gap = (
        fetch_single_asset_data(ticker)
    )
    records_futuros.append({
        "Contrato": nome,
        "Ticker": ticker,
        "Fech. Ant.": fmt_br(prev_c, 2),
        "Abertura": fmt_br(open_p, 2),
        "Preço": fmt_br(price, 2),
        "Var (%)": pct,
        "Gap (%)": gap,
        "Direção": f"{direction} {source}",
    })

  df_futuros = pd.DataFrame(records_futuros)

  styled_df_futuros = (
      df_futuros.style.map(color_variation, subset=["Var (%)", "Gap (%)"])
      .map(color_direction, subset=["Direção"])
      .format({"Var (%)": lambda v: fmt_pct(v), "Gap (%)": lambda v: fmt_pct(v)})
  )

  st.dataframe(styled_df_futuros, width="stretch", hide_index=True)


# =========================================================================
# ABA 5: ORAÇÃO
# =========================================================================
elif aba_ativa == "Oração":
  st.subheader("🙏 Momento de Clareza e Preparação Diária")

  st.markdown(
      """
      <div style="padding: 20px 24px; border-radius: 12px; border: 1px solid #1E88E5; background-color: rgba(30, 136, 229, 0.05); line-height: 1.6; font-size: 1.05rem;">
          <p><b>Pai,</b></p>
          <p>Te rendo graças porque o Senhor é bom e sempre nos ouve. Obrigado pela sua graça e misericórdia que não têm fim. Eu assumo o compromisso de viver uma nova vida, de construir uma nova identidade. Eu ativo a minha identidade. Eu te peço discernimento e clareza para tomar as decisões dentro daquilo que eu estudei. Eu assumo o compromisso de romper e desbloquear a escassez que me faz sentir que vou perder tudo o tempo todo. Eu clarifico o meu propósito, que é governar sobre o meu corpo, sobre as minhas decisões e não de ser governada por ele. Eu coloco o meu corpo na posição de desfrute e de total inclinação para aquilo que vou chamar.</p>
          <p>Nessa manhã de hoje, o meu cérebro é higienizado. Eu deixo os hábitos antigos e tóxicos para trás e me volto para o agora, aqui e agora. Eu deixo a dor da perda para trás porque eu nunca perco, ou eu ganho ou eu aprendo. Eu vou viver novos hábitos no trading porque sei que novos comportamentos exigem repetição. Estou disposto a repetir todos os dias a postura do trader que quero ser.</p>
          <p>A partir de agora, o meu único alvo é caminhar debaixo do favor de Deus e ser fiel ao meu propósito de ser consistente no mercado. Eu vou analisar com clareza e decidir com lucidez. Eu vou governar todos os dias e nada vai me fazer parar. Eu tenho a força do leão e a visão da águia.</p>
          <p><b>Amém.</b></p>
      </div>
      """,
      unsafe_allow_html=True,
  )