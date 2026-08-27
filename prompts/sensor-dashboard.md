# Home sensor dashboard

I've got about 10 ESP32 boards scattered around the house, each reading temperature and humidity and posting the reading as JSON over HTTP every 30 seconds. I want to build a proper little system for this instead of the janky logging script I have now.

Need an endpoint that accepts the posts from the sensors, stores the readings somewhere, and a web dashboard to look at them. On the dashboard I want to see the current temp/humidity for each room at a glance, plus charts showing the last day and last week per room so I can see trends.

Backend should be Python since that's what I know best and what the rest of my home automation stuff is written in. Don't really care what you use for plotting or the frontend, whatever's quick to get running and doesn't look terrible. Each sensor reports its room name in the payload so you don't need to hardcode a sensor list, just take whatever comes in. Keep it simple enough that I can run it on a Raspberry Pi alongside my other stuff.
