import {Form, Button} from 'react-bootstrap'
import {Link} from 'react-router-dom'
import useTheme from '../hooks/useTheme'
import './SiteHeader.css'

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
  const excludedMods = settings?.excluded_mods ?? []
  const exactMods = settings?.exact_mods ?? false

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
    if (!updateSetting) return

    const isRequired = currentMods.includes(mod)
    const isExcluded = excludedMods.includes(mod)

    if (exactMods) {
      if (!isRequired && !isModCompatible(mod)) return

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
                    const isRequired = currentMods.includes(mod)
                    const isExcluded = excludedMods.includes(mod)
                    const isDisabled = exactMods && !isModCompatible(mod)

                    return (
                      <Form.Check
                        inline
                        type="checkbox"
                        id={`header-mod-${mod}`}
                        label={mod}
                        key={mod}
                        checked={isRequired && !isExcluded}
                        disabled={isDisabled}
                        className="mb-0"
                        style={{
                          cursor: isDisabled ? 'not-allowed' : 'pointer',
                        }}
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