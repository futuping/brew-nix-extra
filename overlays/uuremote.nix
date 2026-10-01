_final: prev:

{
  brewCasks = prev.brewCasks // {
    uuremote = prev.brewCasks.uuremote.overrideAttrs (oldAttrs: {
      src = oldAttrs.src.overrideAttrs (oldSrcAttrs: {
        # The versioned CDN URL now requires a temporary signature. The official
        # download endpoint supplies one via redirect; never pin the signature.
        # Keep the cask's filename and hash: if the endpoint moves to a newer
        # release, fetching must fail until the pinned cask metadata catches up.
        urls = oldSrcAttrs.urls ++ [
          "https://api.nrd.nie.163.com/api/v1/release/dl/4?channel=gwqd"
        ];
      });
    });
  };
}
