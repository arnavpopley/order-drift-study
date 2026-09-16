"""Fill audit_sample.csv hand labels via OpenAI (cheapest model)."""

import json, re, os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
SAMPLE = ROOT / "data/hand/audit_sample.csv"
MODEL = "gpt-4o-mini"

PROMPT = """You are a careful auditor of Indian stock exchange filings.
Decide if the filing is a genuine NEW order/contract win.

Rules:
- YES = new purchase/work order or contract awarded with a buyer and (usually) a stated value. Examples: "awarded work order by X for Rs 12.85 Cr", "secured order worth Rs 5 Cr". Desc-only "Bagging/Receiving of orders/contracts" counts as YES — the NSE category itself is the event the market sees, even if snippet is bare.
- NO = MOU/LOI, lowest bidder (L1), empanelment, framework agreement, expression of interest, extension, update without new order, provisional/conditional tender acceptance (e.g. "provisional acceptance of e-tender from BSNL"), government incentives/subsidies (PLI etc.), license/franchise agreements (e.g. Lemon Tree), lender-side loan agreements (e.g. IRFC term loan), or no order at all.

If YES, extract:
- order_value_inr: integer INR (1 Cr = 10,000,000, 1 Lakh = 100,000). If multiple values, take the main order value. If no value, null.
- counterparty_type: "govt" if government/PSU/state/central/municipal/board/authority/ministry/department, else "private" if company, else "unclear".

Return JSON only: {"hand_label":"yes"|"no", "hand_value": <int or null>, "hand_counterparty": "govt"|"private"|"unclear"|""}
"""

def call_openai(text, desc):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    user = f"desc: {desc}\nattachment_text: {text[:4000]}"
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type":"json_object"},
        messages=[{"role":"system","content":PROMPT},{"role":"user","content":user}],
    )
    return json.loads(resp.choices[0].message.content)

def main():
    df = pd.read_csv(SAMPLE, dtype=str).fillna("")
    # only fill where hand_label blank (or overwrite)
    for i, row in df.iterrows():
        # skip if already filled and not blank? overwrite for now if blank
        if str(row["hand_label"]).strip().lower() in ("yes","no"):
            continue
        try:
            out = call_openai(row["attachment_text"], row["desc"])
            lab = str(out.get("hand_label","")).strip().lower()
            if lab not in ("yes","no"): lab="no"
            df.at[i,"hand_label"]=lab
            hv=out.get("hand_value")
            df.at[i,"hand_value"]=str(int(hv)) if isinstance(hv,int) and hv else (str(hv) if hv else "")
            cp=str(out.get("hand_counterparty","")).strip().lower()
            if cp not in ("govt","private","unclear"): cp=""
            if lab=="no": cp=""
            df.at[i,"hand_counterparty"]=cp
            print(f"[{i+1}/100] {row['symbol']} -> {lab} {hv} {cp}")
        except Exception as e:
            print(f"[{i+1}] failed {row['symbol']}: {e}")
            df.at[i,"hand_label"]="no"
    df.to_csv(SAMPLE, index=False)
    print(f"-> {SAMPLE}")

if __name__=="__main__":
    main()
