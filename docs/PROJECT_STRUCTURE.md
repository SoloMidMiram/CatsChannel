# Target Structure

```text
src/
  app/                 # composition root, settings, async session factory
  social/
    handlers.py
    service.py
    repository.py
    states.py
    callbacks.py
    schemas.py
```

Tests mirror `app` and `social`.

## Conflict

The bootstrap structure listed `telegram/`, `cats/`, `moderation/`, `persistence/`, and `common/` as siblings. The anonymous-wall inspection puts this feature in Social and separates routing, thread logic, and persistence as modules inside that boundary. This tree follows the inspection. `cat_reply/` is deferred until `social/` needs a subpackage. Moderation code lands in the Social service and repository in phase 4, not in a second domain package.
