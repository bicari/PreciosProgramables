function handleEnterCantidad(event) {
    const codigosExistentes = new Map()
        const celdas = document.querySelectorAll('#search-results td[data-codigo]');
        celdas.forEach(cell => {
        const codigo = cell.dataset.codigo;
        const valor = parseInt(cell.innerText.trim()) || 0;

        if (codigosExistentes.has(codigo)) {
            const acumulado = codigosExistentes.get(codigo);
            codigosExistentes.set(codigo, acumulado + valor);
        } else {
            codigosExistentes.set(codigo, valor);
        }
    });
    let valorTotal = 0
    if (event.key === 'Enter') {
        event.preventDefault();
        const cell = event.target;
        cell.blur(); // saca el foco de la celda
        const codigo = cell.dataset.codigo;
        const valor = parseInt(cell.innerText.trim()) || 0;
        if (codigosExistentes.has(codigo)){
            valorTotal = codigosExistentes.get(codigo);   
            } 
        console.log(`Código: ${codigo}, Cantidad: ${valor}`);
        console.log(cell);
        const codigoNoEncontrado = actualizarEstadoRecepcion(codigo, valorTotal !== undefined ? valorTotal : valor);
        if (codigoNoEncontrado){
            cell.classList.add('table-danger');
        }
    }
    else{
        celdas.forEach(cell => {
        const codigo = cell.dataset.codigo;
        const valor = parseInt(cell.innerText.trim()) || 0;
        
        if (codigosExistentes.has(codigo)){
            valorTotal = codigosExistentes.get(codigo);   
            } 
        const codigoNoEncontrado = actualizarEstadoRecepcion(codigo, valorTotal !== undefined ? valorTotal : valor)
        
        if (codigoNoEncontrado){
            cell.classList.add('table-danger');
        }
});
    }
}  
  function actualizarEstadoRecepcion(codigo, cantidadRecibida) {
    const filaOC = document.querySelector(`#search-orden-compra tr[data-codigo="${codigo}"]`);
    if (!filaOC) return codigo;

    const pendienteCell = filaOC.querySelector('.pendiente');
    const recibidoCell = filaOC.querySelector('.recibido');
    const pendiente = parseInt(pendienteCell.dataset.pendiente);

    filaOC.classList.remove('table-success', 'table-warning', 'table-danger');

    if (cantidadRecibida === pendiente) {
      filaOC.classList.add('table-success'); 
    } else if (cantidadRecibida > pendiente) {
      filaOC.classList.add('table-warning'); 
    } else {
      filaOC.classList.add('table-danger'); 
    }
    const diferenciaCell = filaOC.querySelector('.diferencia');
    const diferencia = cantidadRecibida - pendiente;
    recibidoCell.innerText = cantidadRecibida;
    diferenciaCell.innerText = diferencia;
    diferenciaCell.dataset.diferencia = diferencia;
  }

function updateTotal(event){
    //const filas = document.querySelectorAll('#search-orden-compra tr');
    const button = event.target
    const codigo = button.dataset.codigo;
    const filaOC = document.querySelector(`#search-orden-compra tr[data-codigo="${codigo}"]`);
    if (!filaOC) return;
    console.log(filaOC);
    filaOC.classList.remove('table-success', 'table-warning', 'table-danger');
    const pendienteCell = filaOC.querySelector('.pendiente');
    const diferenciaCell = filaOC.querySelector('.diferencia');
    const pendienteValue = parseInt(pendienteCell.dataset.pendiente);
    diferenciaCell.innerText = pendienteValue;
    

    
}
function postSearchActions(event){
    document.getElementById('search-producto').value = '';
    handleEnterCantidad(event);
    
}
    
function addProductModal(event){
  const button = event.currentTarget;
  const filaOriginal = button.closest('tr');
  const tbodyProductos = document.getElementById('search-results');

  // Clona el <tr> completo
  const filaClonada = filaOriginal.cloneNode(true);

  // Elimina la última celda (que contiene el botón original)
  const ultimaCelda = filaClonada.querySelector('td:last-child');
  if (ultimaCelda) filaClonada.removeChild(ultimaCelda);

  // Crea nueva celda con botón de eliminación
  const codigo = filaOriginal.dataset.codigo;
  const tdBoton = document.createElement('td');
  tdBoton.innerHTML = `
    <button data-codigo="${codigo}" class="btn btn-danger"
            hx-delete="/product-delete/"
            hx-on:htmx:after-request="updateTotal(event)">
      <i class="fa-solid fa-trash"></i>
    </button>
  `;
  filaClonada.appendChild(tdBoton);
  console.log(filaClonada);
  // Agrega la fila clonada al tbody
  tbodyProductos.appendChild(filaClonada);
  htmx.process(filaClonada);
}

document.body.addEventListener('htmx:afterSwap', (event) => {
  console.info('Evento disparado');
  const tabla = document.getElementById('search-orden-compra');
  const tablaProductos = document.getElementById('search-results');
  const totalizar = document.getElementById('totalizar-documento');

  if (!tabla || !tablaProductos || !totalizar) return;

  const mostrar = tabla.rows.length > 0 && tablaProductos.rows.length > 0 ;
  console.info(`Mostrando totalizar: ${mostrar}`);
  totalizar.classList.toggle('hidden', !mostrar); 

  const buttonProcesar = document.getElementById('procesar-recepcion');
  if (buttonProcesar && !buttonProcesar.dataset.listenerAdded) {
    buttonProcesar.dataset.listenerAdded = 'true';
    buttonProcesar.addEventListener('click', (event) => {
      console.log('Procesando recepción de productos...');
    }, { once: true });
  }
});

document.body.addEventListener('htmx:afterSettle', (event) =>{
  console.info('Evento outerHTML disparado');const totalizarDocumento = document.getElementById('totalizar-documento');
  const tabla = document.getElementById('search-orden-compra');
  const tablaProductos = document.getElementById('search-results');
  console.info('Antes de validar la vvisilidabb', tablaProductos.rows.length, tabla.rows.length);
  if ( tablaProductos.rows.length === 0 ||tabla.rows.length === 0 ){
      console.info('Ocultando totalizar documento');  
      totalizarDocumento.classList.add('hidden');      
    }
    
})

document.body.addEventListener("htmx:error", function (event) {
  
  if ([404, 500].includes(event.detail.errorInfo.xhr.status)) {
    console.info(event.detail)
    const responseText = event.detail.errorInfo.xhr.responseText;
    if (event.detail.elt.id === "search-orden" || event.detail.elt.id ==="search-proveedor"){
        const errorOrden = document.getElementById('error-orden');
        errorOrden.innerHTML = responseText;
        errorOrden.classList.remove('d-none', 'error');
        void errorOrden.offsetWidth;
        errorOrden.classList.add('error');           
      }
    if (event.detail.elt.id === "search-producto"){
        const errorOrden = document.getElementById('error-product');
        errorOrden.innerHTML = responseText;
        errorOrden.classList.remove('d-none', 'error');
        void errorOrden.offsetWidth;
        errorOrden.classList.add('error');
      }      
  }
  
});

document.getElementById("menu-toggle").addEventListener("click", function() {
            const menu = document.querySelector(".nav-side-menu");
            const content = document.querySelector(".main-content");

            menu.classList.toggle("collapsed");
            content.classList.toggle("expanded");
        });
      

document.getElementById("procesar-modal").addEventListener("click", (event)=>{
    const productosOrden = document.querySelectorAll('#search-orden-compra tr');
    const productosRecepcion = document.querySelectorAll('#search-results tr');
    const clasesAfiltrar = ['table-success', 'table-warning', 'table-danger'];
    const filasFiltradas = Array.from(productosOrden).filter(tr =>
    clasesAfiltrar.some(clase => tr.classList.contains(clase))
  );
  const productosRecibidos = Array.from(productosRecepcion).map(tr =>
    Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim())
  );
  const valoresFiltrados = filasFiltradas.map(tr =>
    Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim())
  );

    console.info(productosOrden.values(), productosRecibidos, filasFiltradas)
  }
)

document.addEventListener("htmx:afterRequest",(event) => {
  console.log('Evento disparado escuchado', event.detail)
  const statusPeticionOrder = event.detail.xhr.status
  if (statusPeticionOrder === 200){

  }
})

function recolectarDatos() {
  const clases = ['table-success', 'table-warning', 'table-danger']
  const ordenes = Array.from(document.querySelectorAll('#search-orden-compra tr'))
  .filter(tr => clases.some(clase => tr.classList.contains(clase)))
  .map(tr => ({
    codigo: tr.cells[0].innerText.trim(),
    orden: tr.cells[1].innerText.trim(),
    cantidad: parseFloat(tr.cells[2].innerText.trim().replace(',', '.')),
    recibido: parseFloat(tr.cells[5].innerText.trim().replace(',', '.')),
    costo: parseFloat(tr.cells[4].innerText.trim().replace(',', '.')),
    iva: parseFloat(tr.cells[6].innerText.trim().replace(',', '.')),
    moneda: tr.cells[7].innerText.trim()
  }));

  const productos = Array.from(document.querySelectorAll('#search-results tr')).map(tr => ({
    sku: tr.cells[0].innerText.trim(),
    descripcion: tr.cells[1].innerText.trim(),
    cantidad: tr.cells[2].innerText.trim()
  }));
  const [rif, proveedor]  =  document.getElementById('card-proveedor').innerText.trim().split('-')
  
  return { ordenes, productos, proveedor, rif };
}
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.startsWith(name + "=")) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

document.getElementById('procesar-modal').addEventListener('click', function () {
  const datos = recolectarDatos();
  console.info(datos)
  fetch('/procesar-recepcion/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken') 
      
    },
    body: JSON.stringify(datos)
  })
  .then(response => response.json())
  .then(data => {
    console.log('Respuesta del servidor:', data);
    // Actualiza el DOM si es necesario
  });
});
