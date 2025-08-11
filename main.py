import io, os
from typing import Optional, Dict, List
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

# ======================== App & Auth ========================
API_KEY = os.getenv("API_KEY", "CHANGE_ME")  # set on Render

app = FastAPI(title="SD Tax Engine", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False
)

def check_key(x_api_key: Optional[str]):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.get("/")
def root():
    return {"status": "ok", "message": "Tax Draft Backend is running"}

@app.get("/ping")
def ping():
    return {"message": "pong"}

# ======================== Models ===========================
class Meta(BaseModel):
    business_name: str
    proprietor_name: str
    pan: str
    dob: str              # YYYY-MM-DD
    fy: str               # e.g., 2024-25

class YearIn(BaseModel):
    # Trading / P&L inputs
    turnover: float = 0
    other_income: float = 0
    opening_stock: float = 0
    purchases: float = 0
    return_inwards: float = 0
    return_outwards: float = 0
    carriage_inward: float = 0
    closing_stock: float = 0
    # Indirect expenses
    salaries: float = 0
    rent_utilities: float = 0
    admin_misc: float = 0
    depreciation_it: float = 0
    finance_costs: float = 0
    other_expenses: float = 0
    # Balance sheet heads / capital
    capital_open: float = 0
    additional_investment: float = 0
    drawings: float = 0
    loans: float = 0
    payables: float = 0
    receivables: float = 0
    fixed_assets: float = 0
    cash_bank: float = 0
    other_assets: float = 0
    other_liab: float = 0

class ExcelRequest(BaseModel):
    meta: Meta
    y1: YearIn
    y2: Optional[YearIn] = None            # optional
    auto_growth: bool = False              # if True and y2 missing, auto-create Y2 from Y1
    growth_pct: float = Field(10, ge=0, le=100)
    enforce_continuity: bool = True        # carry forward stock & capital

class ComputeRequest(BaseModel):
    # Very light compute API (optional)
    meta: Meta
    y1: YearIn

class ComputeResponse(BaseModel):
    net_profit: float
    total_income: float
    tax: float
    cess: float
    total_tax_liability: float

# ======================== Helpers ==========================
BOLD = Font(bold=True); HDR = Font(size=12, bold=True)
CENTER = Alignment(horizontal="center", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")
THIN = Border(left=Side(style="thin"), right=Side(style="thin"),
              top=Side(style="thin"), bottom=Side(style="thin"))
FILL = PatternFill("solid", fgColor="F2F2F2")

def inr(x: float) -> float:
    return float(round(x or 0))

def apply_growth(base: YearIn, g: float) -> YearIn:
    f = 1 + g/100.0
    def s(v): return v * f
    return YearIn(**{k: s(getattr(base, k)) for k in base.model_dump().keys()})

def compute_profit(y: YearIn) -> Dict[str, float]:
    net_sales = y.turnover - y.return_inwards
    net_purchases = y.purchases - y.return_outwards
    cogs = y.opening_stock + net_purchases + y.carriage_inward - y.closing_stock
    gross_profit = net_sales - cogs
    indirect = y.salaries + y.rent_utilities + y.admin_misc + y.depreciation_it + y.finance_costs + y.other_expenses
    net_profit = gross_profit + y.other_income - indirect
    return {"net_sales": net_sales, "cogs": cogs, "gross_profit": gross_profit,
            "indirect": indirect, "net_profit": net_profit}

def simple_tax(TI: float) -> Dict[str, float]:
    # Demo new-regime slabs; replace with exact law later
    TI = max(0.0, TI)
    bands = [(300000,0.0),(400000,0.05),(300000,0.10),(200000,0.15),(300000,0.20),(10**18,0.30)]
    t, rem = 0.0, TI
    for width, rate in bands:
        slab = min(rem, width)
        t += slab * rate
        rem -= slab
        if rem <= 0: break
    cess = 0.04 * t
    return {"tax": inr(t), "cess": inr(cess), "total": inr(t+cess)}

def header_block(ws, meta: Meta, title: str):
    ws.append([title]); ws["A1"].font = HDR
    ws.append([f"Business Name: {meta.business_name}"])
    ws.append([f"Proprietor Name: {meta.proprietor_name}"])
    ws.append([f"PAN: {meta.pan}"])
    ws.append([f"Date of Birth: {meta.dob}"])
    ws.append([f"Financial Year: {meta.fy}"])
    ws.append([""])

def t_table(ws, left_rows: List[List], right_rows: List[List]):
    ws.append(["Particulars", "Amount (₹)", "Particulars", "Amount (₹)"])
    for c in range(1,5):
        ws.cell(ws.max_row, c).font = BOLD
        ws.cell(ws.max_row, c).alignment = CENTER
        ws.cell(ws.max_row, c).fill = FILL
        ws.cell(ws.max_row, c).border = THIN
    maxlen = max(len(left_rows), len(right_rows))
    for i in range(maxlen):
        L = left_rows[i] if i < len(left_rows) else ["", 0]
        R = right_rows[i] if i < len(right_rows) else ["", 0]
        ws.append([L[0], inr(L[1] or 0), R[0], inr(R[1] or 0)])
        for col in (2,4):
            cell = ws.cell(ws.max_row, col)
            cell.number_format = "#,##0"; cell.alignment = RIGHT; cell.border = THIN
        for col in (1,3):
            ws.cell(ws.max_row, col).border = THIN
    ws.append([""])

def pl_t(y: YearIn) -> Dict[str, List[List]]:
    # Build P&L T-format (Dr/Cr)
    dr = [
        ["To Opening Stock", y.opening_stock],
        ["To Purchases", y.purchases],
        ["(-) Return Outwards", -y.return_outwards],
        ["To Carriage Inward", y.carriage_inward],
        ["To Salaries", y.salaries],
        ["To Rent & Utilities", y.rent_utilities],
        ["To Admin & Misc", y.admin_misc],
        ["To Finance Costs", y.finance_costs],
        ["To Depreciation (IT)", y.depreciation_it],
        ["To Other Expenses", y.other_expenses],
    ]
    cr = [
        ["By Sales", y.turnover],
        ["(-) Return Inwards", -y.return_inwards],
        ["By Closing Stock", y.closing_stock],
        ["By Other Income", y.other_income],
    ]
    total_dr = sum(x[1] for x in dr)
    total_cr = sum(x[1] for x in cr)
    if total_cr >= total_dr:
        dr.append(["To Net Profit", total_cr - total_dr])
    else:
        cr.append(["By Gross Profit", total_dr - total_cr])
    np = compute_profit(y)["net_profit"]
    return {"dr": dr, "cr": cr, "net_profit": np}

def capital_t(opening: float, profit: float, addl_invest: float, drawings: float):
    cr = [["By Opening Balance", opening], ["By Profit", profit], ["By Additional Investment", addl_invest]]
    dr = [["To Drawings", drawings]]
    tot_cr = sum(x[1] for x in cr); tot_dr = sum(x[1] for x in dr)
    closing = max(0.0, tot_cr - tot_dr)
    dr.append(["To Closing Balance", closing])
    return {"dr": dr, "cr": cr, "closing": closing}

def balance_sheet_t(capital: float, y: YearIn):
    liabilities = [["Capital", capital], ["Loans", y.loans], ["Payables", y.payables], ["Other Liabilities", y.other_liab]]
    assets = [["Fixed Assets", y.fixed_assets], ["Inventory", y.closing_stock], ["Receivables", y.receivables],
              ["Cash/Bank", y.cash_bank], ["Other Assets", y.other_assets]]
    tot_l = sum(x[1] for x in liabilities); tot_a = sum(x[1] for x in assets)
    if tot_l > tot_a: assets.append(["Balancing Figure (Assets)", tot_l - tot_a])
    elif tot_a > tot_l: liabilities.append(["Balancing Figure (Liabilities)", tot_a - tot_l])
    return {"liabilities": liabilities, "assets": assets}

# ======================== COMPUTE (JSON) ====================
def _compute_result(y: YearIn) -> ComputeResponse:
    np = inr(compute_profit(y)["net_profit"])
    tx = simple_tax(np)
    return ComputeResponse(
        net_profit=np, total_income=np,
        tax=tx["tax"], cess=tx["cess"], total_tax_liability=tx["total"]
    )

@app.post("/compute", response_model=ComputeResponse)
def compute_post(payload: ComputeRequest, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    return _compute_result(payload.y1)

# Trailing slash twin to avoid redirects
@app.post("/compute/", response_model=ComputeResponse)
def compute_post_slash(payload: ComputeRequest, x_api_key: Optional[str] = Header(None)):
    return compute_post(payload, x_api_key)

# ======================== EXCEL (3 sheets) ==================
@app.post("/excel")
def excel_post(payload: ExcelRequest, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)

    meta, y1 = payload.meta, payload.y1
    notes: List[str] = []
    y2 = payload.y2
    growth_used = None

    # Auto-generate Y2 if requested
    if not y2 and payload.auto_growth:
        y2 = apply_growth(y1, payload.growth_pct)
        growth_used = payload.growth_pct
        notes.append(f"Year-2 auto-generated at +{growth_used}%.")

    # Enforce continuity
    if y2 and payload.enforce_continuity:
        y2.opening_stock = y1.closing_stock
        notes.append("Continuity: Y1 closing stock carried as Y2 opening stock.")
        # capital continuity handled when building capital accounts

    # Compute profits
    np1 = inr(compute_profit(y1)["net_profit"])
    cap1 = capital_t(y1.capital_open, np1, y1.additional_investment, y1.drawings)
    cap1_close = cap1["closing"]

    np2 = None
    if y2:
        np2 = inr(compute_profit(y2)["net_profit"])
        # opening capital for Y2
        cap2_open = cap1_close if payload.enforce_continuity else y2.capital_open
        notes.append(f"Continuity: Y1 closing capital ({inr(cap1_close)}) used as Y2 opening capital.")
        cap2 = capital_t(cap2_open, np2, y2.additional_investment, y2.drawings)
        cap2_close = cap2["closing"]

    # Workbook
    wb = Workbook()

    # ---- Sheet 1: P&L T-format ----
    ws1 = wb.active; ws1.title = "Profit & Loss"
    header_block(ws1, meta, "Trading and Profit & Loss Account")
    ws1.append(["Year-1"]); ws1["A"+str(ws1.max_row)].font = BOLD
    pl1 = pl_t(y1); t_table(ws1, pl1["dr"], pl1["cr"])

    if y2:
        ws1.append(["Year-2" + (f" (Adjusted @ {growth_used}%)" if growth_used else "")]); ws1["A"+str(ws1.max_row)].font = BOLD
        pl2 = pl_t(y2); t_table(ws1, pl2["dr"], pl2["cr"])

    # ---- Sheet 2: Balance Sheet then Capital A/c (T-format) ----
    ws2 = wb.create_sheet("Balance Sheet & Capital")
    header_block(ws2, meta, "Balance Sheet")
    # Y1
    ws2.append(["Year-1"]); ws2["A"+str(ws2.max_row)].font = BOLD
    bs1 = balance_sheet_t(cap1_close, y1); t_table(ws2, bs1["liabilities"], bs1["assets"])
    ws2.append(["Proprietor's Capital Account"]); ws2["A"+str(ws2.max_row)].font = BOLD
    t_table(ws2, cap1["dr"], cap1["cr"])
    # Y2
    if y2:
        ws2.append(["Year-2" + (f" (Adjusted @ {growth_used}%)" if growth_used else "")]); ws2["A"+str(ws2.max_row)].font = BOLD
        cap2_open = cap1_close if payload.enforce_continuity else y2.capital_open
        cap2_stmt = capital_t(cap2_open, np2, y2.additional_investment, y2.drawings)
        bs2 = balance_sheet_t(cap2_stmt["closing"], y2); t_table(ws2, bs2["liabilities"], bs2["assets"])
        ws2.append(["Proprietor's Capital Account"]); ws2["A"+str(ws2.max_row)].font = BOLD
        t_table(ws2, cap2_stmt["dr"], cap2_stmt["cr"])

    # ---- Sheet 3: Computation (vertical) ----
    ws3 = wb.create_sheet("Computation of Income")
    header_block(ws3, meta, "Computation of Total Income (Demo)")
    def comp_block(label: str, profit: float):
        ws3.append([label]); ws3["A"+str(ws3.max_row)].font = BOLD
        tax = simple_tax(profit)
        rows = [
            ("Income from Business or Profession", profit),
            ("Add: Other Income", 0),
            ("Gross Total Income", profit),
            ("Less: Chapter VI-A", 0),
            ("Total Income", profit),
            ("Tax on Total Income", tax["tax"]),
            ("Add: Health & Education Cess", tax["cess"]),
            ("Total Tax Liability", tax["total"]),
            ("Less: Taxes Paid (TDS/TCS/Adv/SAT)", 0),
            ("Net Tax Payable / (Refund)", tax["total"]),
        ]
        ws3.append(["Particulars", "Amount (₹)"])
        for c in (1,2):
            ws3.cell(ws3.max_row, c).font = BOLD
            ws3.cell(ws3.max_row, c).alignment = CENTER
            ws3.cell(ws3.max_row, c).fill = FILL
            ws3.cell(ws3.max_row, c).border = THIN
        for k, v in rows:
            ws3.append([k, inr(v)])
            ws3.cell(ws3.max_row, 1).border = THIN
            cell = ws3.cell(ws3.max_row, 2); cell.border = THIN; cell.alignment = RIGHT; cell.number_format = "#,##0"
        ws3.append([""])
    comp_block("Year-1", np1)
    if y2: comp_block("Year-2" + (f" (Adjusted @ {growth_used}%)" if growth_used else ""), np2)

    # ---- Notes ----
    notes_ws = wb.create_sheet("Notes"); notes_ws["A1"] = "Notes"; notes_ws["A1"].font = HDR
    r = 3
    for n in notes:
        notes_ws[f"A{r}"] = f"• {n}"; r += 1

    # Return file
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Tax_Report.xlsx"'}
    )

# Trailing-slash twin to avoid redirects
@app.post("/excel/")
def excel_post_slash(payload: ExcelRequest, x_api_key: Optional[str] = Header(None)):
    return excel_post(payload, x_api_key)
