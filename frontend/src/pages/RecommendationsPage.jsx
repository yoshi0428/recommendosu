import {useEffect, useRef, useState} from 'react'
import {
  Alert,
  Container,
} from 'react-bootstrap'

import RecommendationBody from '../components/recommendations/RecommendationBody'
import {getRecommendations} from '../api/client'

import {
  createDefaultSettings,
  normalizeSettings,
} from '../utils/recommendation'

import SiteHeader from '../components/SiteHeader.jsx'
import RecommendationSettingsModal from '../components/recommendations/RecommendationSettingsModal.jsx'

function RecommendationsPage({
                               user,
                               logout,
                             }) {
  const [settings, setSettings] = useState(
    createDefaultSettings
  )

  const [recommendations, setRecommendations] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selectedRecommendation, setSelectedRecommendation] = useState(null)

  // Reference to hold the active AbortController for requests
  const abortControllerRef = useRef(null)

  // Automatically hide the breakdown notification after 2 seconds
  useEffect(() => {
    if (!selectedRecommendation) {
      return
    }

    const timer = setTimeout(() => {
      setSelectedRecommendation(null)
    }, 2000)

    return () => clearTimeout(timer)
  }, [selectedRecommendation])

  useEffect(() => {
    if (user?.player_id == null) {
      return
    }

    setSettings((current) => {
      if (current.player_id !== null) {
        return current
      }

      return {
        ...current,
        player_id: user.player_id,
      }
    })
  }, [user])

  const updateSetting = (key, value) => {
    setSettings((current) => ({
      ...current,
      [key]: value,
    }))
  }

  const updateNestedSetting = (
    key,
    name,
    value,
  ) => {
    setSettings((current) => ({
      ...current,
      [key]: {
        ...current[key],
        [name]: value,
      },
    }))
  }

  const handleSubmit = async () => {
    // 1. If an active request exists, abort it immediately
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    // 2. Create a fresh controller for this request
    const controller = new AbortController()
    abortControllerRef.current = controller

    setLoading(true)
    setError(null)

    try {
      const requestSettings = normalizeSettings(settings)

      // 3. Pass the signal down
      const data = await getRecommendations(
        requestSettings,
        {signal: controller.signal}
      )

      // If this request was aborted, ignore response updates
      if (controller.signal.aborted) return

      const nextRecommendations =
        Array.isArray(data?.recommendations)
          ? data.recommendations
          : Array.isArray(data)
            ? data
            : []

      setRecommendations(nextRecommendations)
    } catch (err) {
      // Catch native fetch aborts or Axios cancellations (CanceledError / ERR_CANCELED)
      if (
        err.name === 'AbortError' ||
        err.code === 'ERR_CANCELED' ||
        err.name === 'CanceledError'
      ) {
        console.log('Recommendation request successfully cancelled.')
        return
      }

      console.error('Recommendation request failed:', err)
      setError(err.message || 'Failed to generate recommendations.')
      setRecommendations([])
    } finally {
      // Only clear loading state if this specific controller is still the active one
      if (abortControllerRef.current === controller) {
        setLoading(false)
        abortControllerRef.current = null
      }
    }
  }

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setLoading(false)
  }

  return (
    // Using 100dvh (dynamic viewport height) handles mobile browser bars and zoom scaling much better than vh-100
    <div className="recommendations-page d-flex flex-column position-relative"
         style={{height: '100dvh', overflow: 'hidden'}}>

      <SiteHeader
        settings={settings}
        updateSetting={updateSetting}
        onRunRecommendations={handleSubmit}
        onCancelRecommendations={handleCancel}
        loading={loading}
        advancedSettingsButton={
          <RecommendationSettingsModal
            user={user}
            logout={logout}
            settings={settings}
            updateSetting={updateSetting}
            updateNestedSetting={updateNestedSetting}
            onRunRecommendations={handleSubmit}
            onCancelRecommendations={handleCancel}
            loading={loading}
          />
        }
      />

      {/* Locked main container with controlled flex scaling */}
      <main className="recommendations-main flex-grow-1 overflow-hidden d-flex flex-column">
        <Container fluid className="recommendations-container py-4 px-4 flex-grow-1 d-flex flex-column overflow-hidden">
          {error && (
            <Alert
              variant="danger"
              dismissible
              onClose={() => setError(null)}
              className="flex-shrink-0 mb-3"
            >
              {error}
            </Alert>
          )}

          <div className="flex-grow-1 overflow-y-auto d-flex flex-column">
            <RecommendationBody
              recommendations={recommendations}
              loading={loading}
              onSelectRecommendation={setSelectedRecommendation}
            />
          </div>
        </Container>
      </main>

      {/* Floating alert banner anchored at the bottom-center */}
      {selectedRecommendation && (
        <div
          className="position-fixed bottom-0 start-50 translate-middle-x mb-3 shadow-lg"
          style={{zIndex: 1050, width: '80%'}}
        >
          <Alert
            variant="info"
            dismissible
            onClose={() => setSelectedRecommendation(null)}
            className="mb-0 border shadow-sm text-center"
          >
            <div className="fw-bold mb-2">
              Breakdown
              for {selectedRecommendation.artist} - {selectedRecommendation.title} [{selectedRecommendation.version}]:
            </div>
            <div className="d-flex flex-wrap justify-content-center gap-3 small">
              <div><strong>Final:</strong> {Number(selectedRecommendation.final_score).toFixed(4)}</div>
              <div><strong>Content:</strong> {Number(selectedRecommendation.content_similarity).toFixed(4)}</div>
              <div><strong>Difficulty:</strong> {Number(selectedRecommendation.difficulty_score).toFixed(4)}</div>
              <div><strong>Mod Preference:</strong> {Number(selectedRecommendation.mod_preference).toFixed(4)}</div>
              <div><strong>Classifier:</strong> {Number(selectedRecommendation.classifier_score).toFixed(4)}</div>
              <div><strong>PP Potential:</strong> {Number(selectedRecommendation.pp_potential).toFixed(4)}</div>
            </div>
          </Alert>
        </div>
      )}
    </div>
  )
}

export default RecommendationsPage