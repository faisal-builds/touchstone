/** ESLint config for the Touchstone TypeScript SDK (eslint 8 + typescript-eslint 7). */
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: 2021, sourceType: "module" },
  plugins: ["@typescript-eslint"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
  ],
  env: { node: true, es2021: true },
  ignorePatterns: ["dist/", "node_modules/", "*.config.ts"],
  rules: {
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/explicit-module-boundary-types": "off",
    "@typescript-eslint/consistent-type-imports": "error",
    "no-console": "off",
  },
};
