// Flat config (eslint.config.mjs) replaces .eslintrc.json, which eslint >=9
// no longer loads. The config object is deliberately global (no `files`
// pattern): with `--config`, pattern bases follow the caller's cwd, so a
// `scripts/*.js` pattern would silently miss the very files CI lints. The
// sanctioned invocations only ever pass scripts/*.js.
import globals from "globals";

export default [
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "commonjs",
      globals: {
        ...globals.node,
      },
    },
    rules: {
      "no-console": "warn",
      "no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          // eslint v9 changed the caughtErrors default to "all"; the codebase
          // uses `catch (_)` as a deliberate ignore placeholder.
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "no-var": "error",
      "prefer-const": "error",
      eqeqeq: ["error", "always"],
      "no-throw-literal": "error",
      "prefer-template": "warn",
      radix: "error",
    },
  },
];
