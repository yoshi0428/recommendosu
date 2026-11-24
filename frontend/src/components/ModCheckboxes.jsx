import { Form } from "react-bootstrap";

// The checkboxes, in the order that they show. bot/options.py has copies of
// these lists.
const INDIVIDUAL_MODS = ["NM", "HD", "HR", "DT", "EZ", "HT", "FL"];

// The mod combinations that have variants in the recommender database.
const MOD_COMBINATIONS = [
  ["HD"],
  ["HR"],
  ["DT"],
  ["EZ"],
  ["HT"],
  ["FL"],
  ["HD", "HR"],
  ["HD", "DT"],
  ["HD", "HR", "DT"],
  ["HR", "DT"],
  ["EZ", "DT"],
  ["EZ", "HD"],
  ["EZ", "HT"],
  ["HD", "HT"],
  ["HR", "HT"],
  ["HD", "HR", "FL"],
  ["HD", "FL"],
  ["HR", "FL"],
  ["DT", "FL"],
];

// One checkbox for each mod. A click moves the mod from required (checked) to
// excluded (indeterminate) to allowed (unchecked). With exact_mods, the checked
// mods are the exact combination, and a mod that cannot extend it is disabled.
// The quick filters of the header (compact) and the Advanced settings use it.
function ModCheckboxes({ settings, updateSetting, idPrefix, compact = false }) {
  const currentMods = settings.mods ?? [];
  const excludedMods = settings.excluded_mods ?? [];
  const exactMods = settings.exact_mods ?? false;

  const isModCompatible = (mod) => {
    if (!exactMods || currentMods.length === 0) return true;
    if (currentMods.includes(mod)) return true;
    if (mod === "NM" || currentMods.includes("NM")) return false;

    const proposedMods = [...currentMods, mod];

    return MOD_COMBINATIONS.some(
      (mods) =>
        mods.length === proposedMods.length &&
        mods.every((m) => proposedMods.includes(m))
    );
  };

  const handleModChange = (mod) => {
    const isRequired = currentMods.includes(mod);
    const isExcluded = excludedMods.includes(mod);

    if (isRequired) {
      updateSetting(
        "mods",
        currentMods.filter((m) => m !== mod)
      );

      // Required -> excluded. (Exact mode has no exclusions.)
      if (!exactMods && !isExcluded) {
        updateSetting("excluded_mods", [...excludedMods, mod]);
      }
      return;
    }

    // Excluded -> allowed
    if (isExcluded && !exactMods) {
      updateSetting(
        "excluded_mods",
        excludedMods.filter((m) => m !== mod)
      );
      return;
    }

    // Allowed -> required
    updateSetting("mods", [...currentMods, mod]);
  };

  return INDIVIDUAL_MODS.map((mod) => {
    const isRequired = currentMods.includes(mod);
    const isExcluded = excludedMods.includes(mod);
    const isDisabled = exactMods && !isModCompatible(mod);

    return (
      <Form.Check
        inline
        type="checkbox"
        id={`${idPrefix}${mod}`}
        label={mod}
        key={mod}
        checked={isRequired && !isExcluded}
        disabled={isDisabled}
        className={compact ? "mb-0" : undefined}
        style={
          compact
            ? { cursor: isDisabled ? "not-allowed" : "pointer" }
            : undefined
        }
        ref={(element) => {
          if (element) {
            element.indeterminate = !exactMods && isExcluded;
          }
        }}
        onChange={() => handleModChange(mod)}
      />
    );
  });
}

export default ModCheckboxes;
