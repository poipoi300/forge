# Expense Splitter

I share a flat with two friends and we're constantly texting each other about who owes what for groceries, utilities, takeout, etc. Want to build a little tool to track this instead.

Basic idea: someone pays for something, we record who paid, how much, and which of the three of us it should be split between (usually all three, but sometimes just two of us order food and the third isn't in on it). Then at any point I want to see a summary of who owes who and how much, ideally simplified so it's not a tangled mess of six different IOUs.

Also need a way to record when someone actually pays another person back, so the balance updates.

Python, and it should just run on my laptop, no need for accounts or auth or anything like that. CLI is fine, or a super minimal local web page if that's not much more work. Data needs to persist between runs obviously. Split evenly among whoever's included for now, don't need percentage splits or anything fancy.
