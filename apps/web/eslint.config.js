import next from "eslint-config-next"

const config = [
  ...next,
  {
    name: "oss-ticketing-web",
    rules: {
      // Keep rules minimal here; prefer upstream Next defaults.
    }
  }
]

export default config
