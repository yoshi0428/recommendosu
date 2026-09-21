import {Card, Form} from 'react-bootstrap'

const INDIVIDUAL_MODS = ['NM', 'HD', 'HR', 'DT', 'EZ', 'HT', 'FL']

function ModOptions({
                      settings,
                      updateSetting,
                    }) {
  const currentMods = settings.mods ?? []
  const excludedMods = settings.excluded_mods ?? []
  const exactMods = settings.exact_mods ?? false

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
        [...excludedMods, mod]
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

    if (enabled) {
      // Exact mode makes unchecked mods allowed rather than excluded.
      updateSetting('excluded_mods', [])
    }
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

            return (
              <Form.Check
                inline
                type="checkbox"
                id={`mod-${mod}`}
                label={mod}
                key={mod}
                checked={isRequired}
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