from osu_tools import OsuCalculator


class VersionAwareOsuCalculator(OsuCalculator):
    """
    OsuCalculator that respects the "osu file format vN" header.

    osu-tools-py constructs LegacyBeatmapDecoder() directly, which
    always decodes as the latest format version (v14). Old maps
    (v3-v5 especially) then get modern stacking instead of the
    legacy stacking osu! uses for them, which inflates aim and
    star rating (e.g. beatmap 1147: 6.56* instead of 5.06*).

    Decoder.GetDecoder reads the header and picks the decoder
    with the correct format version, matching osu-web.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # type: ignore
        from osu.Game.Beatmaps import Beatmap

        # type: ignore
        from osu.Game.Beatmaps.Formats import Decoder

        self._get_decoder = Decoder.GetDecoder[Beatmap]

    def _load_working_beatmap(self, abs_path, ruleset):
        fs = None
        reader = None
        try:
            fs = self.FileStream(abs_path, self.FileMode.Open, self.FileAccess.Read, self.FileShare.Read)
            reader = self.LineBufferedReader(fs)
            beatmap = self._get_decoder(reader).Decode(reader)

            original_ruleset_id = beatmap.BeatmapInfo.Ruleset.OnlineID
            converter = ruleset.CreateBeatmapConverter(beatmap)
            if converter.CanConvert():
                beatmap = converter.Convert()

            return beatmap, self.FlatWorkingBeatmap(beatmap), original_ruleset_id
        finally:
            if reader:
                reader.Dispose()
            if fs:
                fs.Dispose()
