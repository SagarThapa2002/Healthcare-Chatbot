function AboutPlaceholder() {
  return (
    <div className="rounded-lg border border-border bg-surface p-6">
      <h2 className="text-base font-semibold text-text">About this prototype</h2>
      <p className="mt-3 text-sm text-muted">
        This Healthcare Chatbot is a university final-year project prototype. It offers
        general health information, basic symptom guidance, and appointment scheduling
        through a simple chat interface.
      </p>
      <p className="mt-3 text-sm text-muted">
        It is a prototype, not a certified medical device, and it does not provide a
        diagnosis. Its responses are general in nature and are not a substitute for advice
        from a qualified healthcare professional. If you think you may have a medical
        emergency, contact emergency services immediately.
      </p>
    </div>
  );
}

export default AboutPlaceholder;
