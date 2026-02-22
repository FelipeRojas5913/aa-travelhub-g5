# aa-travelhub-g5
El presente repositorio contiene los experimentos relacionado a TravelHub y arquitecturas ágiles.

## Ejecución de los experimentos en Docker
1. Comprobar la versión de Docker en el sistema operativo:

```
docker --version
```

2. Instalar Docker en Linux, recuerde que al usar sudo, debe ingresar su contraseña de acceso:

```
sudo apt install docker.io docker-compose -y
```

3. Comprobar la versión de Docker Compose en el sistema operativo:

```
docker --version
docker-compose --version
```

4. En caso de que su ambiente se encuentre activo en VSCode, debe detenerlo para que se pueda ejecutar los experimentos:

```
deactivate .venv 
```

5. Ejecutar los experimentos:

```
cd travelhub-experiment/
docker-compose up --build
```

6. Para consultar el estado de los servicios, abra una nueva terminal y ejecute los siguientes comandos:

```
curl http://localhost:5000/busqueda/health
curl http://localhost:5001/inventario/health
curl http://localhost:5002/ordenes/health
curl http://localhost:5003/reservas/health
curl http://localhost:5004/usuarios/health
```

7. El resultado debe ser similar al siguiente:

```
{
  "service": "busqueda",
  "status": "healthy",
  "timestamp": "2026-02-21 20:27:36 -05"
}
{
  "service": "inventario",
  "status": "healthy",
  "timestamp": "2026-02-21 20:27:36 -05"
}
{
  "service": "ordenes",
  "status": "healthy",
  "timestamp": "2026-02-21 20:27:36 -05"
}
{
  "service": "reservas",
  "status": "healthy",
  "timestamp": "2026-02-21 20:27:36 -05"
}
{
  "service": "usuarios",
  "status": "healthy",
  "timestamp": "2026-02-21 20:27:36 -05"
}
```

8. En la terminal de VSCode donde ejecuta Docker, revise el status de los servicios, estos deben aparecer en done y en verde.

9. Para finalizar el experimento, presione Ctrl + C en la terminal y ejecute el siguiente comando en la terminal de VSCode donde ejecuta Docker:

```
sudo docker-compose down
```
