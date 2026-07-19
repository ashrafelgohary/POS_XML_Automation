"use strict";
const fileInput=document.getElementById("xmlFile");
const dropZone=document.getElementById("dropZone");
const selectedFile=document.getElementById("selectedFile");
const form=document.getElementById("uploadForm");
const button=document.getElementById("submitButton");
function showFile(file){selectedFile.textContent=file?file.name:"";}
fileInput.addEventListener("change",()=>showFile(fileInput.files[0]));
["dragenter","dragover"].forEach(name=>dropZone.addEventListener(name,event=>{event.preventDefault();dropZone.classList.add("dragging");}));
["dragleave","drop"].forEach(name=>dropZone.addEventListener(name,event=>{event.preventDefault();dropZone.classList.remove("dragging");}));
dropZone.addEventListener("drop",event=>{if(!event.dataTransfer.files.length)return;const transfer=new DataTransfer();transfer.items.add(event.dataTransfer.files[0]);fileInput.files=transfer.files;showFile(fileInput.files[0]);});
form.addEventListener("submit",()=>{button.disabled=true;button.classList.add("loading");button.querySelector(".button-label").textContent="Validating and deploying...";});
const result=document.getElementById("deploymentResult");if(result)result.scrollIntoView({behavior:"smooth",block:"start"});
