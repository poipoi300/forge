# Need this to work on the train

A couple of us commute by train and the wifi is garbage, so the board becomes basically unusable whenever the connection drops. I'd like it to keep working offline — being able to view the board, add and edit cards, move them around — and then have all of that sync up automatically once we're back online.

The tricky part is what happens when two people touched different cards while offline, those should both just merge in fine when everyone reconnects. But if two people happen to edit the exact same card while both offline, I don't want whichever one syncs last to just silently wipe out the other person's changes. I'm fine with something reasonable happening there, doesn't need to be perfect, just shouldn't lose someone's edit without at least surfacing it somehow.

Not looking for a full native app or anything, just want the web app to be resilient when the connection is flaky instead of falling over.
