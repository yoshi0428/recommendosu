import { useId } from "react";
import { Form } from "react-bootstrap";

// A labelled number field for the Advanced settings. An emptied field sends
// emptyValue: null ("no filter") for filters, 0 for weights.
function NumberInput({
  label,
  value,
  onChange,
  step = "any",
  emptyValue = 0,
  className,
  style,
  labelClassName,
}) {
  // controlId links the label to the input (clicking the label focuses it,
  // and screen readers announce the input by its label).
  const id = useId();

  return (
    <Form.Group controlId={id} className={className} style={style}>
      <Form.Label className={labelClassName}>{label}</Form.Label>
      <Form.Control
        type="number"
        value={value ?? ""}
        step={step}
        onChange={(e) =>
          onChange(e.target.value === "" ? emptyValue : Number(e.target.value))
        }
      />
    </Form.Group>
  );
}

export default NumberInput;
