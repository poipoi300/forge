# Static site generator

I want to build a static site generator in Rust for my own blog. I'm sick of existing SSGs like Hugo and Zola being way more complicated than I need — I just write markdown posts and want them turned into HTML.

Each post is a markdown file with front matter at the top: title, date, and a list of tags. I want templates for individual post pages, an index page listing posts, and per-tag pages showing just the posts with that tag. There should also be a static assets folder (css, images, whatever) that just gets copied over as-is into the output.

A `build` command should take my source directory and spit out a folder I can deploy anywhere (rsync it to a server, whatever). I also want a `serve` command for local writing — runs a local server and rebuilds automatically when I save a file, so I can just have it open in a browser tab while I write.

Keep dependencies minimal, I don't want to pull in half of crates.io for this. Doesn't need to be fancy, just fast and predictable.
