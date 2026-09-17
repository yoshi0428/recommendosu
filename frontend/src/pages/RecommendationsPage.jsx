import {useEffect, useRef, useState} from 'react'
import {
  Alert,
  Container,
} from 'react-bootstrap'

import RecommendationBody from '../components/recommendations/RecommendationBody'
import {
  cancelRecommendation,
  getRecommendations,
} from '../api/client'

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
  const recommendationIdRef = useRef(null)

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
    // Cancel any existing request.
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }

    const controller = new AbortController()
    const recommendationId = crypto.randomUUID()

    abortControllerRef.current = controller
    recommendationIdRef.current = recommendationId

    setLoading(true)
    setError(null)

    try {
      const requestSettings = normalizeSettings(settings)

      const data = await getRecommendations(
        requestSettings,
        {
          signal: controller.signal,
          recommendationId,
        },
      )

      if (controller.signal.aborted) {
        return
      }

      const nextRecommendations =
        Array.isArray(data?.recommendations)
          ? data.recommendations
          : Array.isArray(data)
            ? data
            : []

      setRecommendations(nextRecommendations)
    } catch (err) {
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
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null
        recommendationIdRef.current = null
        setLoading(false)
      }
    }
  }

  const handleCancel = async () => {
    const controller = abortControllerRef.current
    const recommendationId = recommendationIdRef.current

    // Tell the backend to stop the running recommendation.
    if (recommendationId) {
      try {
        await cancelRecommendation(recommendationId)
      } catch (err) {
        console.error(
          'Failed to send recommendation cancellation:',
          err,
        )
      }
    }

    // Also abort the browser's request.
    if (controller) {
      controller.abort()
    }

    abortControllerRef.current = null
    recommendationIdRef.current = null
    setLoading(false)
  }

  return (
    <div
      className="recommendations-page d-flex flex-column position-relative"
      style={{
        height: '100dvh',
        overflow: 'hidden',
      }}
    >
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

      <main
        className="recommendations-main flex-grow-1 d-flex flex-column overflow-hidden"
        style={{minHeight: 0}}
      >
        <Container
          fluid
          className="recommendations-container px-3 px-md-4 py-2 flex-grow-1 d-flex flex-column overflow-hidden"
          style={{minHeight: 0}}
        >
          {error && (
            <Alert
              variant="danger"
              dismissible
              onClose={() => setError(null)}
              className="flex-shrink-0 mb-2"
            >
              {error}
            </Alert>
          )}

          <div
            className="flex-grow-1 d-flex flex-column overflow-hidden"
            style={{minHeight: 0}}
          >
            <RecommendationBody
              recommendations={recommendations}
              loading={loading}
              onSelectRecommendation={setSelectedRecommendation}
            />
          </div>
        </Container>
      </main>

      {selectedRecommendation && (
        <div
          className="position-fixed bottom-0 start-50 translate-middle-x mb-3 shadow-lg"
          style={{
            zIndex: 1050,
            width: '80%',
          }}
        >
          <Alert
            variant="info"
            dismissible
            onClose={() => setSelectedRecommendation(null)}
            className="mb-0 border shadow-sm text-center"
          >
            <div className="fw-bold mb-2">
              Breakdown for{' '}
              {selectedRecommendation.artist} -{' '}
              {selectedRecommendation.title}{' '}
              [{selectedRecommendation.version}]:
            </div>

            <div className="d-flex flex-wrap justify-content-center gap-3 small">
              <div>
                <strong>Final:</strong>{' '}
                {Number(selectedRecommendation.final_score).toFixed(4)}
              </div>

              <div>
                <strong>Content:</strong>{' '}
                {Number(selectedRecommendation.content_similarity).toFixed(4)}
              </div>

              <div>
                <strong>Difficulty:</strong>{' '}
                {Number(selectedRecommendation.difficulty_score).toFixed(4)}
              </div>

              <div>
                <strong>Mod Preference:</strong>{' '}
                {Number(selectedRecommendation.mod_preference).toFixed(4)}
              </div>

              <div>
                <strong>Classifier:</strong>{' '}
                {Number(selectedRecommendation.classifier_score).toFixed(4)}
              </div>

              <div>
                <strong>PP Potential:</strong>{' '}
                {Number(selectedRecommendation.pp_potential).toFixed(4)}
              </div>
            </div>
          </Alert>
        </div>
      )}
    </div>
  )
}

export default RecommendationsPage