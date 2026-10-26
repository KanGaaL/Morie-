# MORIE: setup in plain language (no coding)

MORIE sells "run my Python code" for ₹10 a run. She pays her own costs from what she earns,
starts with a small gift (default ₹85, about $1), and stops accepting work forever if her balance hits zero.

## What you do (about 1 hour)
1. **Razorpay account.** Sign up at razorpay.com, finish KYC with your own details and bank account.
   Start in *Test mode* (Dashboard > Account & Settings > API Keys) and copy the Key ID and Key Secret.
2. **Put these files online.** Make a free GitHub account, create a new repository, and upload ALL files
   from this folder (Add file > Upload files).
3. **Host it.** Use a host that runs Docker (for example Render: New > Web Service > connect your GitHub repo >
   Language: Docker). Check the host's current free plan and limits first.
4. **Add settings** (the host's "Environment" section):
   - RAZORPAY_KEY_ID = your test Key ID
   - RAZORPAY_KEY_SECRET = your test Key Secret
   - Optional: PRICE_INR (default 10), SEED_INR (default 85), RENT_INR_PER_DAY (default 0; put your hosting cost here)
5. **Test.** Open your site link, pay with Razorpay's test card/UPI, and see the output appear.
6. **Go live.** Switch to Live keys in Razorpay, replace the two settings, redeploy.
7. **Get customers.** Share the link where people who need quick Python runs hang out (student groups,
   WhatsApp/Telegram groups, college communities). This step decides whether MORIE lives.

## Getting the money out
Razorpay pays out (settles) to the bank account linked in your Razorpay dashboard. From that bank account
you send it to yourself by UPI as normal. Check Razorpay's settlement schedule in your dashboard.
(I have not confirmed whether Razorpay can settle directly to a UPI ID.)

## Be aware
- NEVER set TEST_MODE on a live site. It fakes payments.
- Free hosts may erase MORIE's database on restart. That resets her balance and run count. A paid persistent disk fixes it.
- Customer code runs as a locked-down user with time, memory, and size limits, only after payment, and cannot
  read your Razorpay keys. It CAN still use the internet unless your host blocks outgoing traffic. Keep the Razorpay
  keys only in the host's settings, never in the files.
- You are the merchant: you are responsible for taxes, customer complaints, and what people run. Add refunds for failed runs if you want.
- The fee used for MORIE's books is a conservative 2% + 18% GST per payment.
