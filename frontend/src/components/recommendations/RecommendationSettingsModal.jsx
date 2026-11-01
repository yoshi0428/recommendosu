import { useState } from "react";
import { Button, Modal } from "react-bootstrap";

import BasicOptions from "../BasicOptions";
import ModOptions from "../ModOptions";
import CandidateFilters from "../CandidateFilters";
import DifficultyProfile from "../DifficultyProfile";
import ScoringOptions from "../ScoringOptions";

function RecommendationSettingsModal({
  settings,
  updateSetting,
  updateNestedSetting,
  onRunRecommendations,
  onCancelRecommendations,
  loading,
}) {
  const [show, setShow] = useState(false);

  const handleClose = () => {
    setShow(false);
  };

  const footerButtonStyle = { minWidth: "min(160px, 40vw)" };

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
        fullscreen="sm-down"
        scrollable
        centered
      >
        <Modal.Header closeButton>
          <Modal.Title>Recommendation Settings</Modal.Title>
        </Modal.Header>

        <Modal.Body>
          <BasicOptions settings={settings} updateSetting={updateSetting} />

          <ModOptions settings={settings} updateSetting={updateSetting} />

          <CandidateFilters settings={settings} updateSetting={updateSetting} />

          <DifficultyProfile
            settings={settings}
            updateNestedSetting={updateNestedSetting}
          />

          <ScoringOptions settings={settings} updateSetting={updateSetting} />
        </Modal.Body>

        <Modal.Footer className="justify-content-center">
          <div className="d-flex gap-2 justify-content-center">
            <Button variant="secondary" onClick={handleClose} style={footerButtonStyle}>
              Close
            </Button>

            {loading ? (
              <Button
                variant="outline-danger"
                onClick={onCancelRecommendations}
                style={footerButtonStyle}
              >
                Cancel Request
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={onRunRecommendations}
                style={footerButtonStyle}
              >
                Run Recommender
              </Button>
            )}
          </div>
        </Modal.Footer>
      </Modal>
    </>
  );
}

export default RecommendationSettingsModal;
