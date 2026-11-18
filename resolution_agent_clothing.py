import json
import os
import uuid

from openai import OpenAI

# Works with OpenAI or any OpenAI-compatible server (like Groq).
# Set OPENAI_API_KEY, OPENAI_BASE_URL and OPENAI_MODEL before running.
client = OpenAI()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_STEPS = 6  # most a normal case needs is 5 model calls

# ------------------------------------------------------------------
# fake database
# ------------------------------------------------------------------
orders = {
    "ORD-1001": {"name": "Aarav Sharma", "email": "aarav@example.com",
                 "item_id": "SKU-TSHIRT-BLK", "item": "Black Cotton T-Shirt",
                 "size": "M", "amount": 24.99,
                 "status": "delivered", "exchange_eligible": True},
    "ORD-1002": {"name": "Meera Singh", "email": "meera@example.com",
                 "item_id": "SKU-JEANS-BLU", "item": "Blue Slim-Fit Jeans",
                 "size": "32", "amount": 59.00,
                 "status": "delivered", "exchange_eligible": True},
    "ORD-1003": {"name": "Rohan Verma", "email": "rohan@example.com",
                 "item_id": "SKU-JACKET-NVY", "item": "Navy Winter Jacket",
                 "size": "L", "amount": 89.50,
                 "status": "delivered", "exchange_eligible": False},
    "ORD-1004": {"name": "Priya Nair", "email": "priya@example.com",
                 "item_id": "SKU-DRESS-RED", "item": "Red Summer Dress",
                 "size": "S", "amount": 45.00,
                 "status": "delivered", "exchange_eligible": True},
}

# stock[item_id][size] = units in the warehouse
stock = {
    "SKU-TSHIRT-BLK": {"S": 0, "M": 8, "L": 3, "XL": 2},
    "SKU-JEANS-BLU": {"30": 4, "32": 0, "34": 6},
    "SKU-JACKET-NVY": {"M": 2, "L": 5, "XL": 1},
    "SKU-DRESS-RED": {"S": 0, "M": 5, "L": 2},
}

refunds = {}
emails_sent = []


# ------------------------------------------------------------------
# tools (each one returns a dict with a status field)
# ------------------------------------------------------------------
def order_lookup(order_id):
    order = orders.get(order_id)
    if not order:
        return {"status": "error", "error": "Order " + order_id + " not found"}
    result = {"status": "success", "order_id": order_id}
    result.update(order)
    return result


def inventory_check(item_id, size):
    if item_id not in stock:
        return {"status": "error", "error": "Item " + item_id + " not found in inventory"}
    size = size.strip().upper()
    sizes = stock[item_id]
    if size not in sizes:
        return {"status": "error",
                "error": "Size " + size + " does not exist for " + item_id,
                "sizes_offered": list(sizes)}
    count = sizes[size]
    return {
        "status": "success",
        "item_id": item_id,
        "size": size,
        "stock": count,
        "in_stock": count > 0,
        "other_sizes_in_stock": [s for s, n in sizes.items() if n > 0 and s != size],
    }


def process_refund(order_id, reason):
    if order_id not in orders:
        return {"status": "error", "error": "Order " + order_id + " not found"}
    if order_id in refunds:
        return {"status": "error", "error": "Order " + order_id + " was already refunded"}
    refund = {
        "refund_reference": "RFND-" + uuid.uuid4().hex[:8].upper(),
        "order_id": order_id,
        "amount_refunded": orders[order_id]["amount"],
        "refunded_to": "original payment method",
        "reason": reason,
    }
    refunds[order_id] = refund
    return dict(refund, status="success")


def send_notification(customer_email, message):
    if "@" not in customer_email:
        return {"status": "error", "error": "Invalid email address"}
    note_id = "NTF-" + uuid.uuid4().hex[:8].upper()
    emails_sent.append({"id": note_id, "to": customer_email, "message": message})
    return {"status": "success", "notification_id": note_id, "to": customer_email}


# ------------------------------------------------------------------
# registry - only these names are allowed to run
# ------------------------------------------------------------------
registry = {
    "order_lookup": order_lookup,
    "inventory_check": inventory_check,
    "process_refund": process_refund,
    "send_notification": send_notification,
}


# ------------------------------------------------------------------
# schemas - this is all the model can see about the tools
# ------------------------------------------------------------------
def make_tool(name, description, params, required):
    properties = {}
    for key, desc in params.items():
        properties[key] = {"type": "string", "description": desc}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


tools = [
    make_tool(
        "order_lookup",
        "Look up an order by its ID. Returns the customer name and email, the clothing "
        "item (item_id and name), the size that was ordered, amount paid, order status and "
        "whether the order is eligible for exchange. Always call this first.",
        {"order_id": "The order ID, for example ORD-1001"},
        ["order_id"],
    ),
    make_tool(
        "inventory_check",
        "Check warehouse stock for ONE size of a clothing item to see if a replacement is "
        "available. Returns the stock count for that size and the other sizes that are in "
        "stock. Use the item_id from order_lookup and the size the customer wants.",
        {"item_id": "The item ID, for example SKU-TSHIRT-BLK",
         "size": "The size to check, for example M, L, XL or 32"},
        ["item_id", "size"],
    ),
    make_tool(
        "process_refund",
        "Issue a financial refund to the customer's original payment method. Only use "
        "this when a replacement is NOT possible: the size needed is out of stock or the "
        "order is not eligible for exchange. Never use it when an exchange is possible.",
        {"order_id": "The order ID to refund",
         "reason": "Short reason for the refund"},
        ["order_id", "reason"],
    ),
    make_tool(
        "send_notification",
        "Send a confirmation email to the customer about the final resolution (exchange "
        "confirmed with item and size, or refund issued with the refund reference). Call it "
        "once at the end. Do not use it for orders that were not found.",
        {"customer_email": "The customer's email from order_lookup",
         "message": "The full text of the email"},
        ["customer_email", "message"],
    ),
]


# ------------------------------------------------------------------
# dispatcher - checks the request before running anything
# ------------------------------------------------------------------
def run_tool(name, raw_args):
    if name not in registry:
        return {"status": "error",
                "error": "Tool '" + name + "' is not allowed. Allowed tools: " + ", ".join(registry)}

    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return {"status": "error", "error": "Arguments were not valid JSON, please try again"}
    if not isinstance(args, dict):
        return {"status": "error", "error": "Arguments must be a JSON object"}

    # find this tool's schema to validate against
    schema = None
    for t in tools:
        if t["function"]["name"] == name:
            schema = t["function"]["parameters"]

    for field in schema["required"]:
        if field not in args:
            return {"status": "error", "error": "Missing required argument: " + field}
    for key, value in args.items():
        if key not in schema["properties"]:
            return {"status": "error", "error": "Unknown argument: " + key}
        if not isinstance(value, str) or not value.strip():
            return {"status": "error", "error": "Argument '" + key + "' must be a non-empty string"}

    try:
        return registry[name](**args)
    except Exception as e:
        return {"status": "error", "error": "Tool crashed: " + str(e)}


# ------------------------------------------------------------------
# the agent loop
# ------------------------------------------------------------------
SYSTEM_PROMPT = """You are a customer support agent for a clothing store. You resolve
problems with orders.

Follow these steps:
1. Call order_lookup with the order ID the customer gave.
   If the order is not found, do not guess anything. Tell the customer the order was
   not found and ask them to check the order ID. Do not refund or send an email.
   If the customer did not give an order ID, ask for it.
2. Work out which size the replacement should be. If the customer asked for a
   particular size (for example "I need a size L instead"), use that size. Otherwise use
   the size from the order. Then call inventory_check with the item_id and that size.
3. If the order is eligible for exchange and stock for that size is more than 0,
   confirm a replacement exchange in that size. Do not refund.
   If stock for that size is 0, or the order is not eligible for exchange, call
   process_refund. (If the size was out of stock, you may mention which other sizes
   are available in your final summary.)
4. Call send_notification once with the customer's email and a clear confirmation.
   Include the item and size, and the refund reference and amount if there was a refund.
5. Reply to the customer with a short, polite summary of what was done.

Only use information from the tools. Never make up order details, sizes, stock numbers
or reference numbers. If a tool returns an error, fix your call or explain the problem."""


def run_agent(user_text):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    for step in range(1, MAX_STEPS + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        reply = response.choices[0].message

        # no tool call means the model is giving its final answer
        if not reply.tool_calls:
            return reply.content or "(no reply from the model)"

        # save the model's tool request in the history
        messages.append({
            "role": "assistant",
            "content": reply.content,
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in reply.tool_calls
            ],
        })

        # run each tool and feed the result back
        for call in reply.tool_calls:
            result = run_tool(call.function.name, call.function.arguments)
            print("   [step %d] %s(%s) -> %s" % (
                step, call.function.name, call.function.arguments, result["status"]))
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })

    # ran out of steps, hand over to a human
    return ("Sorry, I couldn't finish resolving this automatically. "
            "I've flagged your case for a human support agent who will contact you.")


# ------------------------------------------------------------------
# main - type customer messages, type quit to stop
# ------------------------------------------------------------------
def main():
    print("Clothing Order Resolution Agent")
    print("Describe your problem and include your order ID (and the size you want, if")
    print("it is different from what you ordered). Type 'quit' to exit.")

    while True:
        text = input("\nCustomer: ").strip()
        if text.lower() in ("quit", "exit", "q"):
            break
        if not text:
            continue
        answer = run_agent(text)
        print("\nAgent: " + answer)

    print("\n--- Refunds issued ---")
    print(json.dumps(refunds, indent=2) if refunds else "None")
    print("--- Emails sent ---")
    print(json.dumps(emails_sent, indent=2) if emails_sent else "None")


if __name__ == "__main__":
    main()
