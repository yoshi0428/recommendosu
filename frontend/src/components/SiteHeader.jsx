import {Form, Button} from 'react-bootstrap'
import {Link} from 'react-router-dom'
import useTheme from '../hooks/useTheme'
import './SiteHeader.css'

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

const INDIVIDUAL_MODS = ['NM', 'HD', 'HR', 'DT', 'EZ', 'HT', 'FL']

const variantArrays = Object.values(MOD_VARIANTS)

// Checks if a candidate set of mods fits inside at least one valid variant combination
const isValidCombination = (mods) => {
  if (mods.length === 0 || (mods.length === 1 && mods.includes('NM'))) return true
  if (mods.includes('NM')) return false

  return variantArrays.some((variant) =>
    mods.every((m) => variant.includes(m))
  )
}

function SiteHeader({
                      rightActions,
                      settings = {},
                      updateSetting,
                      onRunRecommendations,
                      onCancelRecommendations,
                      loading,
                      advancedSettingsButton,
                      logout,
                    }) {
  const {theme, toggleTheme} = useTheme()
  const currentMods = settings?.mods ?? []

  const handleModChange = (mod) => {
    if (!updateSetting) return

    let nextMods

    if (mod === 'NM') {
      if (currentMods.includes('NM')) {
        nextMods = []
      } else {
        nextMods = ['NM']
      }
    } else {
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
    if (mod === 'NM') return false

    const filteredMods = currentMods.filter((m) => m !== 'NM')

    return !isValidCombination([...filteredMods, mod])
  }

  const handleNumberChange = (key, value) => {
    if (!updateSetting) return

    updateSetting(
      key,
      value === '' ? null : Number(value)
    )
  }

  const handleSubmit = (e) => {
    e.preventDefault()

    if (loading) {
      onCancelRecommendations?.()
    } else {
      onRunRecommendations?.()
    }
  }

  return (
    <header className="border-bottom py-2">
      <div className="container-fluid px-3 px-md-4">

        <div className="row align-items-center g-2">

          {/* Left side: Coffee button */}
          <div className="col-12 col-lg-2 d-flex justify-content-center justify-content-lg-start">
            <a
              href="https://buymeacoffee.com/recommendosu"
              target="_blank"
              rel="noopener noreferrer"
              className={`btn btn-sm text-decoration-none text-nowrap ${
                theme === 'dark'
                  ? 'btn-outline-warning'
                  : 'btn-outline-secondary'
              }`}
            >
              Buy me a coffee! ☕
            </a>
          </div>

          {/* Center section */}
          <div className="col-12 col-lg-8">
            <div className="quick-mods d-flex flex-column align-items-center gap-2 text-center">

              <h1 className="mb-0 fs-4">
                osu! Beatmap Recommender
              </h1>

              <Form
                onSubmit={handleSubmit}
                className="
                  d-flex
                  align-items-center
                  justify-content-center
                  flex-wrap
                  gap-1 gap-md-2
                  small
                  text-muted
                  w-100
                "
              >

                {/* Stars Quick Filter */}
                <div className="d-flex align-items-center gap-1">
                  <span className="fw-semibold">Stars:</span>

                  <Form.Control
                    type="number"
                    size="sm"
                    placeholder="Min"
                    value={settings.min_stars ?? ''}
                    step="0.1"
                    style={{width: '60px'}}
                    onChange={(e) =>
                      handleNumberChange('min_stars', e.target.value)
                    }
                  />

                  <span>-</span>

                  <Form.Control
                    type="number"
                    size="sm"
                    placeholder="Max"
                    value={settings.max_stars ?? ''}
                    step="0.1"
                    style={{width: '60px'}}
                    onChange={(e) =>
                      handleNumberChange('max_stars', e.target.value)
                    }
                  />
                </div>

                {/* BPM Quick Filter */}
                <div className="d-flex align-items-center gap-1">
                  <span className="fw-semibold">BPM:</span>

                  <Form.Control
                    type="number"
                    size="sm"
                    placeholder="Min"
                    value={settings.min_bpm ?? ''}
                    step="1"
                    style={{width: '60px'}}
                    onChange={(e) =>
                      handleNumberChange('min_bpm', e.target.value)
                    }
                  />

                  <span>-</span>

                  <Form.Control
                    type="number"
                    size="sm"
                    placeholder="Max"
                    value={settings.max_bpm ?? ''}
                    step="1"
                    style={{width: '60px'}}
                    onChange={(e) =>
                      handleNumberChange('max_bpm', e.target.value)
                    }
                  />
                </div>

                {/* PP Quick Filter */}
                <div className="d-flex align-items-center gap-1">
                  <span className="fw-semibold">PP:</span>

                  <Form.Control
                    type="number"
                    size="sm"
                    placeholder="Min"
                    value={settings.min_pp ?? ''}
                    step="1"
                    style={{width: '65px'}}
                    onChange={(e) =>
                      handleNumberChange('min_pp', e.target.value)
                    }
                  />

                  <span>-</span>

                  <Form.Control
                    type="number"
                    size="sm"
                    placeholder="Max"
                    value={settings.max_pp ?? ''}
                    step="1"
                    style={{width: '65px'}}
                    onChange={(e) =>
                      handleNumberChange('max_pp', e.target.value)
                    }
                  />
                </div>

                {/* Quick Mod Checkboxes */}
                <div className="d-flex flex-wrap align-items-center gap-2 ps-3">
                  {INDIVIDUAL_MODS.map((mod) => {
                    const isChecked = currentMods.includes(mod)
                    const disabled = isModDisabled(mod)

                    return (
                      <Form.Check
                        inline
                        type="checkbox"
                        id={`header-mod-${mod}`}
                        label={mod}
                        key={mod}
                        checked={isChecked}
                        disabled={disabled}
                        className={`mb-0 ${
                          disabled ? 'opacity-50' : ''
                        }`}
                        style={{
                          cursor: disabled
                            ? 'not-allowed'
                            : 'pointer',
                        }}
                        onChange={() => handleModChange(mod)}
                      />
                    )
                  })}
                </div>

                {/* Run / Advanced Settings */}
                <div className="d-flex align-items-center gap-2 flex-nowrap">
                  {loading ? (
                    <Button
                      type="button"
                      variant="outline-danger"
                      size="sm"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        onCancelRecommendations?.()
                      }}
                    >
                      Cancel
                    </Button>
                  ) : (
                    <Button
                      type="submit"
                      variant="primary"
                      size="sm"
                    >
                      Apply & Run
                    </Button>
                  )}

                  {advancedSettingsButton}
                </div>

              </Form>
            </div>
          </div>

          {/* Right side */}
          <div className="col-12 col-lg-2">
            <div className="d-flex align-items-center justify-content-center justify-content-lg-end gap-2">
              {rightActions}

              {/* About */}
              <Button
                as={Link}
                to="/about"
                variant="outline-secondary"
                size="sm"
              >
                About
              </Button>


              {/* Theme */}
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={toggleTheme}
                aria-label="Toggle color theme"
              >
                {theme === 'dark' ? '☀' : '🌙'}
              </button>

              {/* Logout */}
              {logout && (
                <Button
                  variant="outline-danger"
                  size="sm"
                  onClick={logout}
                >
                  Logout
                </Button>
              )}
            </div>
          </div>

        </div>
      </div>
    </header>
  )
}

export default SiteHeader
