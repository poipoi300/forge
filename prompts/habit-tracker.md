# Habit Tracker CLI

Want to build a little CLI for tracking daily habits, mostly for myself. Basic idea: I define a handful of habits (like "meditate", "read", "exercise"), and each day I check them off from the terminal. I want to be able to see my current streak for each habit so I have some motivation to not break the chain.

Should be a Python project using uv for dependency management, and I'd like it typed (type hints throughout, maybe run mypy at some point). Data should just live in a local file next to the project, nothing fancy like a real database.

Rough commands I'm picturing: something to add a new habit, something to mark a habit done for today, and something to show a status view with all habits and their current streaks. Keep the output readable in a terminal, doesn't need to be fancy.

This is a weekend project so let's keep it simple to start. I can always add more later.
