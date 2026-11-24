// Tests for pages/Terms.jsx and pages/Privacy.jsx, and for the links to them.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import AuthScreen from "@/components/AuthScreen";
import About from "@/pages/About";
import Privacy from "@/pages/Privacy";
import Terms from "@/pages/Terms";

describe.each([
  ["Terms of Service", Terms, "Privacy Policy", "/privacy"],
  ["Privacy Policy", Privacy, "Terms of Service", "/terms"],
])("%s", (title, Page, otherTitle, otherPath) => {
  it("shows its title and links to the other page", () => {
    render(
      <MemoryRouter>
        <Page />
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
    const links = screen.getAllByRole("link", { name: otherTitle });
    expect(links.map((link) => link.getAttribute("href"))).toContain(otherPath);
  });
});

it.each([
  ["login screen", AuthScreen],
  ["About page", About],
])("the %s links to both pages", (_, Page) => {
  render(
    <MemoryRouter>
      <Page />
    </MemoryRouter>
  );

  expect(screen.getByRole("link", { name: "Terms of Service" })).toHaveAttribute("href", "/terms");
  expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
});
