from anime_api.sources.dramacool import DramaCool

dc = DramaCool()
for cat in ("cdrama", "kdrama"):
    items = dc.home("latest", category=cat)
    print(cat, "home:", len(items))
    for it in items[:4]:
        try:
            d = dc.details(it["id"])
            ep = d["seasons"][0]["episodes"][0]
            s = dc.streams(ep["data"])
            print(" ", it["title"][:38], "| streams:", len(s["streams"]),
                  s["streams"][0]["type"] if s["streams"] else "-",
                  (s["streams"][0]["url"][:70] if s["streams"] else ""))
        except Exception as e:
            print(" ", it["title"][:38], "EXC", str(e)[:80])
