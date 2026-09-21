import {Card, Form} from 'react-bootstrap'

const INDIVIDUAL_MODS = ['NM', 'HD', 'HR', 'DT', 'EZ', 'HT', 'FL']

const MOD_VARIANTS = {
  "HD": ["HD"],
  "HR": ["HR"],
  "DT": ["DT"],
  "EZ": ["EZ"],
  "HT": ["HT"],
  "FL": ["FL"],
  "HDHR": ["HD", "HR"],
  "HDDT": ["HD", "DT"],
  "HDHRDT": ["HD", "HR", "DT"],
  "HRDT": ["HR", "DT"],
  "EZDT": ["EZ", "DT"],
  "EZHD": ["EZ", "HD"],
  "EZHT": ["EZ", "HT"],
  "HDHT": ["HD", "HT"],
  "HRHT": ["HR", "HT"],
  "HDHRFL": ["HD", "HR", "FL"],
  "HDFL": ["HD", "FL"],
  "HRFL": ["HR", "FL"],
  "DTFL": ["DT", "FL"],
}

function ModOptions({
                      settings,
                      updateSetting,
                    }) {
  const currentMods = settings.mods ?? []
  const excludedMods = settings.excluded_mods ?? []
  const exactMods = settings.exact_mods ?? false

  const isModCompatible = (mod) => {
    if (!exactMods || currentMods.length === 0) return true
    if (currentMods.includes(mod)) return true
    if (mod === 'NM' || currentMods.includes('NM')) return false

    const proposedMods = [...currentMods, mod]

    return Object.values(MOD_VARIANTS).some(
      (mods) =>
        mods.length === proposedMods.length &&
        mods.every((m) => proposedMods.includes(m))
    )
  }

  const handleModChange = (mod) => {
    const isRequired = currentMods.includes(mod)
    const isExcluded = excludedMods.includes(mod)

    // Exact combination mode:
    // checked mods are the only mods allowed.
    if (exactMods) {
      if (isRequired) {
        updateSetting(
          'mods',
          currentMods.filter((m) => m !== mod)
        )
      } else {
        updateSetting(
          'mods',
          [...currentMods, mod]
        )
      }

      return
    }

    // Normal required / excluded / allowed behavior
    if (isRequired) {
      updateSetting(
        'mods',
        currentMods.filter((m) => m !== mod)
      )
      updateSetting(
        'excluded_mods',
        excludedMods.includes(mod)
          ? excludedMods
          : [...excludedMods, mod]
      )
      return
    }

    if (isExcluded) {
      updateSetting(
        'excluded_mods',
        excludedMods.filter((m) => m !== mod)
      )
      return
    }

    updateSetting('mods', [...currentMods, mod])
  }

  const handleExactModsChange = (enabled) => {
    updateSetting('exact_mods', enabled)

    // Reset mod selection when switching modes.
    updateSetting('mods', [])
    updateSetting('excluded_mods', [])
  }

  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Mods</strong>
      </Card.Header>

      <Card.Body>
        <Form.Check
          type="switch"
          id="exact-mods"
          label="Exact combination"
          checked={exactMods}
          onChange={(event) =>
            handleExactModsChange(event.target.checked)
          }
          className="mb-3"
        />

        <div className="d-flex flex-wrap gap-4">
          {INDIVIDUAL_MODS.map((mod) => {
            const isRequired = currentMods.includes(mod)
            const isExcluded = excludedMods.includes(mod)
            const isDisabled = exactMods && !isModCompatible(mod)

            return (
              <Form.Check
                inline
                type="checkbox"
                id={`mod-${mod}`}
                label={mod}
                key={mod}
                checked={isRequired && !isExcluded}
                disabled={isDisabled}
                ref={(element) => {
                  if (element) {
                    element.indeterminate = !exactMods && isExcluded
                  }
                }}
                onChange={() => handleModChange(mod)}
              />
            )
          })}
        </div>
      </Card.Body>
    </Card>
  )
}

export default ModOptions