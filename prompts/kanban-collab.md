# Kanban collab board

My team is 5 people and we're tired of Trello's limitations, so I want to build our own shared kanban board. Boards, columns, cards with a title, description, and assignee, and you can drag cards around between columns. The main thing is it needs to feel realtime — if I move a card, everyone else looking at the board sees it move without hitting refresh.

TypeScript across the whole stack, that's non-negotiable. For the realtime part, websockets or whatever else fits naturally, your call. We're self-hosting this on our own box, no cloud dependencies we can avoid.

Keep the UI simple for now, closer to a basic Trello clone than anything fancy. I mostly care about the collaboration feeling solid and instant, since that's the whole point of building this instead of just using a spreadsheet. Let me know what stack you land on before you go too far.
