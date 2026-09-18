# Instructions on how to research crash incidents

Given a crash record with id:
bb0df05fbedbb24ac65a350806e3d4cd78bf6715a52bf2c82c5fe88df88e2c3650246ad7855d3f17e1a323bebc0d57095c92fdbd54b5a762186ca8cae7843616

Which has an info profile (`./q info [crash_record_id]`) of:

```
    2026-07-25 19:11
    2155 N LAKE SHORE DR NB, lincoln-park
    OTHER
    fatalities: 1 injured: 0
    - 20 M FATAL DRIVER
```

Do a web search for news stories, starting out with a query with the specific address and date:

```
chicago july 25 2026 crash 2155 n lake shore dr
```

If no stories are found using the exact address, then try a rounded (to the 100) block address, and add the neighborhood e.g.

```
chicago july 25 2026 crash lincoln park 2100 n lake shore dr
```

Prioritize these local news sources:

- abc7chicago.com,ABC 7 Chicago
- fox32chicago.com,FOX 32 Chicago
- nbcchicago.com,NBC 5 Chicago
- chicago.suntimes.com,Chicago Sun-Times
- chicagotribune.com,Chicago Tribune
- chi.streetsblog.org,Chicago Streetsblog
- blockclubchicago.org,Block Club Chicago
  https://www.cbsnews.com/chicago/,CBS News Chicago
  wgntv.com,WGN-TV


For sites like wgntv.com that block auto-fetching, add a story item with just the URL and site attributes filled out

## When finding valid related stories

When finding a valid story URL, populate the information as specified in `./q clip --id [crash_record_id] [url`

After adding the story item, add the `autosearched` attribute and set it to true

Finally, if the private_notes attribute has the boilerplate "This entry is just a stub, pre-filled with basic info from the crash data:", remove that line IF you were able to find a story

### Followups

If any of the found stories contains a victim's or suspect's name, do a secondary search to find followup stories:

```
chicago crash [year of crash] [victim/suspect name]
```



## When no stories were found

However, if no relevant stories were found, set `search_status` to "autosearched-empty"


