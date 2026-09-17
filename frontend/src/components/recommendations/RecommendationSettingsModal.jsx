import {useState} from 'react'
import {
  Button,
  Modal,
} from 'react-bootstrap'

import BasicOptions from '../BasicOptions'
import ModOptions from '../ModOptions'
import CandidateFilters from '../CandidateFilters'
import DifficultyProfile from '../DifficultyProfile'
import ScoringOptions from '../ScoringOptions'


function RecommendationSettingsModal({
                                       settings,
                                       updateSetting,
                                       updateNestedSetting,
                                       onRunRecommendations,
                                       onCancelRecommendations,
                                       loading,
                                     }) {
  const [show, setShow] = useState(false)

  const handleClose = () => {
    setShow(false)
  }

  const handleRun = () => {
    onRunRecommendations?.()
  }

  const handleCancelLoading = (e) => {
    e?.preventDefault()
    e?.stopPropagation()
    onCancelRecommendations?.()
  }

  return (
    <>
      <Button
        variant="outline-secondary"
        size="sm"
        onClick={() => setShow(true)}
      >
        Advanced
      </Button>

      <Modal
        show={show}
        onHide={handleClose}
        size="xl"
        scrollable
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>
            Recommendation Settings
          </Modal.Title>
        </Modal.Header>

        <Modal.Body>
          <BasicOptions
            settings={settings}
            updateSetting={
              updateSetting
            }
          />

          <ModOptions
            settings={settings}
            updateSetting={
              updateSetting
            }
          />

          <CandidateFilters
            settings={settings}
            updateSetting={
              updateSetting
            }
          />

          <DifficultyProfile
            settings={settings}
            updateNestedSetting={
              updateNestedSetting
            }
          />

          <ScoringOptions
            settings={settings}
            updateSetting={
              updateSetting
            }
          />
        </Modal.Body>

        <Modal.Footer className="justify-content-center">
          {loading ? (
            <div className="d-flex gap-2 justify-content-center">
              <Button
                variant="secondary"
                onClick={handleClose}
                style={{minWidth: '160px'}}
              >
                Close
              </Button>

              <Button
                variant="outline-danger"
                onClick={handleCancelLoading}
                style={{minWidth: '160px'}}
              >
                Cancel Request
              </Button>
            </div>
          ) : (
            <div className="d-flex gap-2 justify-content-center">
              <Button
                variant="secondary"
                onClick={handleClose}
                style={{minWidth: '160px'}}
              >
                Close
              </Button>

              <Button
                variant="primary"
                onClick={handleRun}
                style={{minWidth: '160px'}}
              >
                Run Recommender
              </Button>
            </div>
          )}
        </Modal.Footer>
      </Modal>
    </>
  )
}

export default RecommendationSettingsModal