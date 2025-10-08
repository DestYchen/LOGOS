export const prettifyFieldKey = (key: string) => {
  return key
    .split(".")
    .map((chunk) =>
      chunk
        .split("_")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
        .join(" "),
    )
    .join(" \u203a ")
}
