from osu_tools import OsuCalculator


class VersionAwareOsuCalculator(OsuCalculator):
    """
    An OsuCalculator that obeys the "osu file format vN" header.

    osu-tools-py makes LegacyBeatmapDecoder() directly, which always decodes
    as the latest format version (v14). Then old maps (v3-v5 especially) get
    the modern stacking, not the legacy stacking that osu! uses for them. This
    makes their aim and star rating too high (for example, beatmap 1147: 6.56*,
    not 5.06*).

    Decoder.GetDecoder reads the header and selects the decoder with the
    correct format version, as osu-web does.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # These .NET modules are available only after OsuCalculator starts the runtime.
        from osu.Game.Beatmaps import Beatmap  # type: ignore
        from osu.Game.Beatmaps.Formats import Decoder  # type: ignore

        self._get_decoder = Decoder.GetDecoder[Beatmap]

    def _load_working_beatmap(self, abs_path, ruleset):
        """The OsuCalculator method, with the decoder of the correct format version."""
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
