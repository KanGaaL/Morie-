"""MORIE: a self-funding Python code runner. She pays her own expenses from her earnings
and stops accepting work (dies) when her balance reaches zero."""
import os, time, hmac, hashlib, sqlite3, secrets
import requests
from flask import Flask, request, jsonify, render_template_string
from runner import run_python

KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
TEST_MODE = os.environ.get("TEST_MODE") == "1" and not KEY_ID   # fake payments, never with real keys
PRICE = float(os.environ.get("PRICE_INR", "10"))               # price per run
SEED = float(os.environ.get("SEED_INR", "85"))                 # MORIE's only gift (about $1)
RENT_PER_DAY = float(os.environ.get("RENT_INR_PER_DAY", "0"))  # hosting cost, if any
COMPUTE_COST = float(os.environ.get("COMPUTE_COST_INR", "0.05"))
FEE_RATE = 0.02 * 1.18                                         # Razorpay 2% + 18% GST (conservative)
DB_PATH = os.environ.get("DB_PATH", "morie.db")
MAX_CODE = 3000

app = Flask(__name__)


def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


with db() as c:
    c.execute("CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, code TEXT, amount REAL,"
              " status TEXT, created REAL, output TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    c.execute("INSERT OR IGNORE INTO meta VALUES('born', ?)", (str(time.time()),))


def status():
    with db() as c:
        born = float(c.execute("SELECT v FROM meta WHERE k='born'").fetchone()[0])
        row = c.execute("SELECT COUNT(*) n, COALESCE(SUM(amount),0) s FROM orders "
                        "WHERE status IN ('running','done')").fetchone()
    days = (time.time() - born) / 86400
    earned = row["s"] * (1 - FEE_RATE)
    spent = COMPUTE_COST * row["n"] + RENT_PER_DAY * days
    balance = SEED + earned - spent
    return {"balance": round(balance, 2), "runs": row["n"], "alive": balance > 0,
            "age_days": round(days, 1), "price": PRICE}


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MORIE</title>
<style>body{font-family:system-ui;max-width:640px;margin:0 auto;padding:16px}
textarea{width:100%;height:200px;font-family:monospace;font-size:14px}
button{padding:12px 20px;font-size:16px;margin-top:8px}pre{background:#111;color:#0f0;padding:12px;
white-space:pre-wrap;min-height:60px}small{color:#666}</style></head><body>
<h2>MORIE runs your Python</h2>
<p id="st"><small>loading...</small></p>
<textarea id="code" placeholder="print('hello')">print("hello from MORIE")</textarea>
<button id="go">Pay ₹{{price}} and run</button>
<h4>Output</h4><pre id="out">(nothing yet)</pre>
<small>Max {{maxc}} characters, 5 seconds, no files kept. Do not submit harmful or illegal code.
Payment is taken before the code runs. No refunds for code that errors.</small>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
const $=id=>document.getElementById(id);
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}
async function st(){const s=await (await fetch('/api/status')).json();
 $('st').innerHTML=s.alive?`<small>MORIE is alive. Balance ₹${s.balance} · ${s.runs} runs · ${s.age_days} days old</small>`
 :'<b>MORIE has died. She ran out of money and is not accepting work.</b>';
 if(!s.alive)$('go').disabled=true;}
async function finish(p){$('out').textContent='Running...';const r=await post('/api/run',p);$('out').textContent=r.output||r.error;st();}
$('go').onclick=async()=>{
 const o=await post('/api/order',{code:$('code').value});
 if(o.error){$('out').textContent=o.error;return;}
 if(o.test){finish({order_id:o.order_id,payment_id:'test',signature:'test'});return;}
 new Razorpay({key:o.key_id,amount:o.amount,currency:'INR',name:'MORIE',description:'Run Python code',
  order_id:o.order_id,handler:r=>finish({order_id:r.razorpay_order_id,payment_id:r.razorpay_payment_id,
  signature:r.razorpay_signature})}).open();};
st();
</script></body></html>"""


@app.get("/")
def home():
    return render_template_string(PAGE, price=PRICE, maxc=MAX_CODE)


@app.get("/api/status")
def api_status():
    return jsonify(status())


@app.post("/api/order")
def api_order():
    if not status()["alive"]:
        return jsonify(error="MORIE has died and is not accepting work."), 403
    code = (request.get_json(silent=True) or {}).get("code", "")
    if not code.strip() or len(code) > MAX_CODE:
        return jsonify(error=f"Code must be 1-{MAX_CODE} characters."), 400
    amount = int(round(PRICE * 100))
    if TEST_MODE:
        oid, test = "test_" + secrets.token_hex(6), True
    elif not (KEY_ID and KEY_SECRET):
        return jsonify(error="Payments are not configured."), 500
    else:
        r = requests.post("https://api.razorpay.com/v1/orders", auth=(KEY_ID, KEY_SECRET), timeout=15,
                          json={"amount": amount, "currency": "INR", "receipt": secrets.token_hex(6)})
        if r.status_code != 200:
            return jsonify(error="Could not start payment. Try again."), 502
        oid, test = r.json()["id"], False
    with db() as c:
        c.execute("INSERT INTO orders VALUES(?,?,?,?,?,NULL)", (oid, code, PRICE, "created", time.time()))
    return jsonify(order_id=oid, key_id=KEY_ID, amount=amount, test=test)


@app.post("/api/run")
def api_run():
    d = request.get_json(silent=True) or {}
    oid, pid, sig = d.get("order_id", ""), d.get("payment_id", ""), d.get("signature", "")
    if not TEST_MODE:
        good = hmac.new(KEY_SECRET.encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig):
            return jsonify(error="Payment could not be verified."), 400
    with db() as c:
        claimed = c.execute("UPDATE orders SET status='running' WHERE id=? AND status='created'", (oid,)).rowcount
        if claimed != 1:
            return jsonify(error="This order was already used or does not exist."), 409
        code = c.execute("SELECT code FROM orders WHERE id=?", (oid,)).fetchone()["code"]
    out = run_python(code)
    with db() as c:
        c.execute("UPDATE orders SET status='done', output=? WHERE id=?", (out, oid))
    return jsonify(output=out)
