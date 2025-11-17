(function () {
  const bookingModal = document.getElementById("bookingModal");
  const bookingForm = document.getElementById("bookingForm");
  if (!bookingModal || !bookingForm) {
    return;
  }
  const bookingButtons = document.querySelectorAll("[data-slot-button]");
  const bookingSlotIdInput = document.getElementById("bookingSlotId");
  const bookingNameInput = document.getElementById("bookingName");
  const bookingEmailInput = document.getElementById("bookingEmail");
  const bookingBreedInput = document.getElementById("bookingBreed");
  const bookingSlotSummary = document.getElementById("bookingSlotSummary");
  const bookingModalClose = document.getElementById("bookingModalClose");
  const bookingModalError = document.getElementById("bookingModalError");
  const bookingSuccess = document.getElementById("bookingSuccess");
  const bookingSubmit = bookingForm.querySelector("button[type='submit']");
  const submitDefaultLabel = bookingSubmit ? bookingSubmit.textContent : "";

  function updateSlotButton(slot) {
    if (!slot) return;
    const button = document.querySelector(`[data-slot-button][data-slot-id="${slot.id}"]`);
    if (!button) return;
    const statusEl = button.querySelector(".slot-card__status");
    const priceEl = button.querySelector(".slot-card__price");
    const isBooked = Boolean(slot.is_booked);
    button.dataset.state = isBooked ? "booked" : "available";
    button.disabled = isBooked;
    button.setAttribute("aria-disabled", isBooked ? "true" : "false");
    button.classList.toggle("is-booked", isBooked);
    if (slot.friendly_label) {
      button.dataset.friendlyLabel = slot.friendly_label;
    }
    if (priceEl && slot.price_label) {
      priceEl.textContent = slot.price_label;
    }
    if (statusEl) {
      statusEl.textContent = isBooked ? "Booked" : "Available";
    }
  }

  function closeBookingModal() {
    bookingModal.classList.add("hidden");
    document.body.classList.remove("modal-open");
    bookingForm.reset();
    if (bookingSlotIdInput) {
      bookingSlotIdInput.value = "";
    }
    if (bookingSlotSummary) {
      bookingSlotSummary.textContent = "";
    }
    bookingModalError.classList.add("hidden");
  }

  function openBookingModal(button) {
    bookingForm.reset();
    if (bookingSlotIdInput) {
      bookingSlotIdInput.value = button.dataset.slotId;
    }
    if (bookingSlotSummary) {
      bookingSlotSummary.textContent = button.dataset.friendlyLabel || "";
    }
    bookingModalError.classList.add("hidden");
    bookingModal.classList.remove("hidden");
    document.body.classList.add("modal-open");
    if (bookingNameInput) {
      setTimeout(() => bookingNameInput.focus(), 50);
    }
  }

  bookingButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.state !== "available") {
        return;
      }
      openBookingModal(button);
    });
  });

  if (bookingModalClose) {
    bookingModalClose.addEventListener("click", closeBookingModal);
  }
  bookingModal.addEventListener("click", (event) => {
    if (event.target === bookingModal) {
      closeBookingModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !bookingModal.classList.contains("hidden")) {
      closeBookingModal();
    }
  });

  bookingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!bookingSlotIdInput || !bookingSlotIdInput.value) {
      return;
    }
    bookingModalError.classList.add("hidden");
    const payload = {
      name: bookingNameInput ? bookingNameInput.value.trim() : "",
      email: bookingEmailInput ? bookingEmailInput.value.trim() : "",
    };
    if (bookingBreedInput) {
      payload.breed_id = bookingBreedInput.value;
    }
    const visitorName = payload.name || "there";
    if (bookingSubmit) {
      bookingSubmit.disabled = true;
      bookingSubmit.textContent = "Booking...";
    }
    const friendlyLabel = bookingSlotSummary ? bookingSlotSummary.textContent : "";
    try {
      const response = await fetch(`/bookings/slots/${encodeURIComponent(bookingSlotIdInput.value)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "Unable to book this slot.");
      }
      if (data.slot) {
        updateSlotButton(data.slot);
      }
      if (bookingSuccess) {
        const label = (data.slot && data.slot.friendly_label) || friendlyLabel;
        bookingSuccess.textContent = `Thanks ${visitorName}! ${label} is now reserved.`;
        bookingSuccess.classList.remove("hidden");
      }
      closeBookingModal();
    } catch (error) {
      bookingModalError.textContent = error.message || "Unable to book this slot.";
      bookingModalError.classList.remove("hidden");
    } finally {
      if (bookingSubmit) {
        bookingSubmit.disabled = false;
        bookingSubmit.textContent = submitDefaultLabel || "Book this slot";
      }
    }
  });
})();
