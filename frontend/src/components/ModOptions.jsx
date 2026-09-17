import {Card, Form} from 'react-bootstrap'

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

const INDIVIDUAL_MODS = [
  'NM',
  'HD',
  'HR',
  'DT',
  'EZ',
  'HT',
  'FL',
]

const variantArrays = Object.values(MOD_VARIANTS)

// Checks if a candidate set of mods fits inside at least one valid variant
const isValidCombination = (mods) => {
  if (mods.length === 0 || (mods.length === 1 && mods.includes('NM'))) return true
  // If NM is present with other mods, it's invalid
  if (mods.includes('NM')) return false
  return variantArrays.some((variant) =>
    mods.every((m) => variant.includes(m))
  )
}

function ModOptions({
                      settings,
                      updateSetting,
                    }) {
  const currentMods = settings.mods ?? []

  const toggleMod = (mod) => {
    let nextMods

    if (mod === 'NM') {
      // Clicking NM clears everything else and toggles NM
      if (currentMods.includes('NM')) {
        nextMods = []
      } else {
        nextMods = ['NM']
      }
    } else {
      // Clicking any other mod removes NM if it was present
      const filteredMods = currentMods.filter((m) => m !== 'NM')

      if (filteredMods.includes(mod)) {
        nextMods = filteredMods.filter((m) => m !== mod)
      } else {
        const next = [...filteredMods, mod]
        if (isValidCombination(next)) {
          nextMods = next
        } else {
          return
        }
      }
    }

    updateSetting('mods', nextMods)
  }

  const isModDisabled = (mod) => {
    if (currentMods.includes(mod)) return false

    if (mod === 'NM') {
      return false // NM is always toggleable unless rules dictate otherwise
    }

    const filteredMods = currentMods.filter((m) => m !== 'NM')
    return !isValidCombination([...filteredMods, mod])
  }

  return (
    <Card className="mb-4">
      <Card.Header>
        <strong>Mods</strong>
      </Card.Header>

      <Card.Body>
        <div className="d-flex flex-wrap gap-4">
          {INDIVIDUAL_MODS.map((mod) => {
            const checked = currentMods.includes(mod)
            const disabled = isModDisabled(mod)

            return (
              <Form.Check
                inline
                type="checkbox"
                id={`mod-${mod}`}
                label={mod}
                key={mod}
                checked={checked}
                disabled={disabled}
                onChange={() => toggleMod(mod)}
              />
            )
          })}
        </div>
      </Card.Body>
    </Card>
  )
}

export default ModOptions