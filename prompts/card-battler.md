# Terminal card battler

I want to build a small roguelike deck-builder combat game that runs in the terminal, written in Rust. No game engine, just clean idiomatic Rust with a simple render loop printing to stdout.

Core loop: player vs a scripted enemy, one fight at a time. Each turn the player draws a hand from their deck, has some energy to spend, and plays cards from hand — attacks, blocks, and a couple of buff cards. The enemy should telegraph what it's going to do next turn (like "enemy will attack for 8" shown above its health bar) so the player can react with block or buffs before ending their turn. When the player ends the turn, resolve the enemy's telegraphed move, then start the next turn.

Keep the card pool small to start, maybe 10-15 cards, and structure it so a full "run" is a sequence of fights rather than just one battle. Player has HP that persists between fights. Doesn't need to be fancy, just something I can build on.
