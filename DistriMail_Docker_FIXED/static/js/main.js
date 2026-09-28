document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".page-alert").forEach(function (element) {
        setTimeout(function () {
            element.style.opacity = "0";
            element.style.transition = "opacity .4s";
        }, 4500);
    });
});

function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    if (sidebar) sidebar.classList.toggle("open");
}

function showFileName(input) {
    const target = document.getElementById("fileName");
    if (!target) return;
    target.textContent = input.files.length ? input.files[0].name : "No file selected · Max 5 MB";
}
