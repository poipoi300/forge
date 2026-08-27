# Inventory + POS for the shop

I run a small family stationery shop and I want a simple program to help manage it, Python with a SQLite database is fine since it's just me and my dad using one computer at the till.

Main things I need: a product catalog with names and prices, and a way to ring up a sale — usually a few different items at once, paid either cash or card. When something sells, the stock count for that product should go down automatically. I want to be able to pull up a low-stock list so we know what to reorder, and at the end of the day I want a summary of total sales, split out by cash vs card, so we can reconcile the till.

Doesn't need to be fancy, just a command-line tool is totally fine for now, maybe a menu of options when you run it. We can add a nicer interface later if it's worth it. Products are things like notebooks, pens, envelopes, that kind of thing, nothing complicated about categories or variants for now.
