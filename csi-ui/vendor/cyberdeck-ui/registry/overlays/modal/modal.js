// Opens <dialog class="cy-modal"> from [data-cy-modal-open="<dialog id>"] buttons.
// Buttons inside <form method="dialog"> close it; clicking the backdrop does too.
document.querySelectorAll('[data-cy-modal-open]').forEach((button) => {
  const dialog = document.getElementById(button.dataset.cyModalOpen);

  button.addEventListener('click', () => dialog.showModal());
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close('cancel');
  });
});
