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
BIZ = os.environ.get("BUSINESS_NAME", "MORIE")
EMAIL = os.environ.get("CONTACT_EMAIL", "")
PHONE = os.environ.get("CONTACT_PHONE", "")
ADDRESS = os.environ.get("CONTACT_ADDRESS", "")

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
<p>An automated online service that runs a short Python program you paste in and shows you its output instantly. Price: ₹{{price}} per run.</p>
<p id="st"><small>loading...</small></p>
<textarea id="code" placeholder="print('hello')">print("hello from MORIE")</textarea>
<button id="go">Pay ₹{{price}} and run</button>
<h4>Output</h4><pre id="out">(nothing yet)</pre>
<small>Max {{maxc}} characters, 5 seconds, no files kept. Do not submit harmful or illegal code.
Payment is taken before the code runs. No refunds for code that errors.</small>
<p><small><a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> · <a href="/refund">Refunds</a> · <a href="/shipping">Delivery</a> · <a href="/contact">Contact</a></small></p>
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


# ---------- policy pages (Razorpay asks for these before approving a website) ----------
from markupsafe import escape, Markup

DOC = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} - {{biz}}</title>
<style>body{font-family:system-ui;max-width:640px;margin:0 auto;padding:16px;line-height:1.5}</style></head>
<body><p><a href="/">&larr; Home</a></p><h2>{{title}}</h2>{{body}}
<hr><small>{{biz}}</small></body></html>"""


def doc(title, html):
    return render_template_string(DOC, title=title, body=Markup(html), biz=BIZ)


def contact_lines():
    out = []
    if EMAIL: out.append(f"Email: {escape(EMAIL)}")
    if PHONE: out.append(f"Phone: {escape(PHONE)}")
    if ADDRESS: out.append(f"Address: {escape(ADDRESS)}")
    return "<br>".join(out) or "Contact details will be added soon."


@app.get("/terms")
def terms():
    return doc("Terms and Conditions", f"""
<p>{escape(BIZ)} ("we") provides an automated online service that runs short Python programs submitted by you
and returns the output. By using it you agree to these terms.</p>
<p><b>Price:</b> Rs {PRICE:g} per run, paid in advance through Razorpay. Prices may change; the price shown at payment applies.</p>
<p><b>Limits:</b> up to {MAX_CODE} characters of code and 5 seconds of run time per run. No files are kept.</p>
<p><b>Your responsibility:</b> do not submit harmful, illegal or abusive code, or code that attacks other systems or people.
We may refuse or stop any run and may block misuse without refund.</p>
<p><b>Availability:</b> the service is provided as is, without guarantees. It may be slow or unavailable at times.
Our liability is limited to the amount you paid for the affected run.</p>
<p><b>Law:</b> these terms are governed by the laws of India.</p>
<p>Questions: <br>{contact_lines()}</p>""")


@app.get("/privacy")
def privacy():
    return doc("Privacy Policy", f"""
<p>We collect only what is needed to run the service: the code you submit, its output, and the payment order and
payment ID. Payments are handled by Razorpay; we never see or store your card, UPI or bank details.</p>
<p>We use this information only to run your code, confirm your payment and keep our accounts. We do not sell or share
it, except with Razorpay for payment processing or when required by law.</p>
<p>Do not put passwords, personal data or secrets in your code. To ask us to delete your stored code and output,
contact us: <br>{contact_lines()}</p>""")


@app.get("/refund")
def refund():
    return doc("Refund and Cancellation Policy", f"""
<p>Each run is paid for before it runs and starts immediately, so a run cannot be cancelled once started.</p>
<p><b>We refund you</b> if your payment succeeded but the run could not be done because of a fault on our side,
or if you were charged twice for one run. Contact us within 7 days with your payment ID.</p>
<p><b>We do not refund</b> runs where the output is an error caused by your own code, a timeout caused by your own code,
or a run stopped for misuse.</p>
<p>Approved refunds are sent to the original payment method; your bank may take a few business days to show it.</p>
<p>Contact: <br>{contact_lines()}</p>""")


@app.get("/shipping")
def shipping():
    return doc("Delivery Policy", """
<p>This is a digital service. Nothing is shipped. The output of your code is shown on the page within seconds after
your payment succeeds. If you paid but saw no output, contact us using the details on the Contact page.</p>""")


@app.get("/contact")
def contact():
    return doc("Contact Us", f"<p><b>{escape(BIZ)}</b></p><p>{contact_lines()}</p>")
