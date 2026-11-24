import { useId } from "react";
import { Form } from "react-bootstrap";

// A number field with a label, for the Advanced settings. An empty field sends
// emptyValue: null ("no filter") for the filters, and 0 for the weights.
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
  // controlId links the label to the input. A click on the label moves the
  // focus to the input, and screen readers read the label for the input.
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
