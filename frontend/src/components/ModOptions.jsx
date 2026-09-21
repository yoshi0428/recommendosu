import {Card, Form} from 'react-bootstrap'

const INDIVIDUAL_MODS = ['NM', 'HD', 'HR', 'DT', 'EZ', 'HT', 'FL']

function ModOptions({
                      settings,
                      updateSetting,
                    }) {
  const currentMods = settings.mods ?? []
  const excludedMods = settings.excluded_mods ?? []

  const handleModChange = (mod) => {
    const isRequired = currentMods.includes(mod)
    const isExcluded = excludedMods.includes(mod)

    // Required -> Excluded
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

    // Excluded -> Allowed
    if (isExcluded) {
      updateSetting(
        'excluded_mods',
        excludedMods.filter((m) => m !== mod)
      )
      return
    }

    // Allowed -> Required
    updateSetting('mods', [...currentMods, mod])
  }

  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Mods</strong>
      </Card.Header>

      <Card.Body>
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
                    element.indeterminate = isExcluded
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