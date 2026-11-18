# Order Resolution Agent

An autonomous tool-using agent that handles customer issues with clothing orders.
It looks up the order, checks warehouse stock for the needed size, then either
confirms an exchange or issues a refund, and sends a confirmation email.

## Setup
pip install -r requirements.txt

export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.groq.com/openai/v1"   # optional, for Groq
export OPENAI_MODEL="openai/gpt-oss-120b"                 # optional

## Run
python resolution_agent_clothing.py

Type a customer message with an order ID, for example:
My T-shirt from ORD-1001 is damaged
Type quit to exit.

## Test order IDs
ORD-1001 (exchange), ORD-1002 (refund, out of stock), ORD-1003 (refund, not
eligible), ORD-1004 (size S out of stock, exchange if size M requested),
ORD-9999 (order not found)