# shellcheck shell=bash
# Sourced by start_combined.sh (#104). Google ADC reads a FILE PATH, but Railway
# delivers the kg-mcp service account as GOOGLE_APPLICATION_CREDENTIALS_JSON
# (devex #13866). Materialise it into a private 0600 file, point
# GOOGLE_APPLICATION_CREDENTIALS at it, and drop the raw JSON from the environment
# so child processes and crash dumps do not carry the key twice.
#
# Never echoes the value. A preset GOOGLE_APPLICATION_CREDENTIALS wins (local dev).
# With neither set this is a no-op; scoped_server then finds no readable credential
# file at boot and disables semantic /query (503, reason on /health) while the typed
# routes stay up. start_combined.sh unsets the path before starting the gateway.
if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS_JSON:-}" && -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  _adc_file="$(umask 077 && mktemp "${TMPDIR:-/tmp}/adc.XXXXXX")"
  printf '%s' "$GOOGLE_APPLICATION_CREDENTIALS_JSON" > "$_adc_file"
  chmod 600 "$_adc_file"
  export GOOGLE_APPLICATION_CREDENTIALS="$_adc_file"
  unset _adc_file
fi
unset GOOGLE_APPLICATION_CREDENTIALS_JSON
