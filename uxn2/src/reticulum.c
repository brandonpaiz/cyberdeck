/*
@|Reticulum --------------------------------------------------------- */

/*
Cyberdeck extension: a frame-passing device on page d0 that connects uxn2
to the cyberdeck bridge over a Unix socket. The device knows nothing about
LXMF; it moves opaque frames (len* + payload) both ways. See DESIGN.md §5.

|d0 @Reticulum &vector $2 &status $1 &queue $1 &count $2 &length $2 &addr $2 &read $1 &write $1 &pad $4

  d0 vector*  write  called once per frame queued for the ROM
  d2 status   read   b0 socket connected, b1 reticulum up, b2 rnode online, b3 frame dropped
  d3 queue    read   frames waiting
  d4 count*   read   bytes moved by the last read/write, 0000 = nothing
  d6 length*  write  buffer size for read / bytes to send for write
  d8 addr*    write  buffer address
  da read     write  pop the oldest frame into addr (at most length bytes)
  db write    write  send length bytes at addr as one frame

Socket path: $CYBERDECK_SOCKET, else $XDG_RUNTIME_DIR/cyberdeck.sock,
else /run/cyberdeck/bridge.sock. Without a bridge the device is inert.
*/

#define RET_MAX_FRAME 1024
#define RET_QUEUE 16
#define RET_TYPE_STATE 0x81

#ifndef _WIN32
#include <sys/socket.h>
#include <sys/un.h>
#include <errno.h>
#define RET_ENABLED 1
#else
#define RET_ENABLED 0
#endif

typedef struct {
	Uint8 *data;
	Uint16 len;
} RetFrame;

static Uint32 ret_event;
static SDL_mutex *ret_lock;
static int ret_fd = -1;
static Uint8 ret_bridge_flags, ret_dropped;
static RetFrame ret_queue[RET_QUEUE];
static int ret_qhead, ret_qlen;

static int
ret_connected(void)
{
	int c;
	if(!ret_lock) return 0;
	SDL_LockMutex(ret_lock);
	c = ret_fd >= 0;
	SDL_UnlockMutex(ret_lock);
	return c;
}

#if RET_ENABLED

static const char *
ret_socket_path(char *buf, size_t cap)
{
	const char *env = getenv("CYBERDECK_SOCKET");
	if(env && *env) return env;
	env = getenv("XDG_RUNTIME_DIR");
	if(env && *env) {
		snprintf(buf, cap, "%s/cyberdeck.sock", env);
		if(access(buf, F_OK) == 0) return buf;
	}
	return "/run/cyberdeck/bridge.sock";
}

static int
ret_connect(void)
{
	char buf[256];
	struct sockaddr_un addr;
	const char *path = ret_socket_path(buf, sizeof(buf));
	int fd = socket(AF_UNIX, SOCK_STREAM, 0);
	if(fd < 0) return -1;
	memset(&addr, 0, sizeof(addr));
	addr.sun_family = AF_UNIX;
	strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);
	if(connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		close(fd);
		return -1;
	}
	return fd;
}

static int
ret_read_full(int fd, Uint8 *dst, size_t n)
{
	while(n) {
		ssize_t r = read(fd, dst, n);
		if(r <= 0) {
			if(r < 0 && errno == EINTR) continue;
			return 0;
		}
		dst += r, n -= r;
	}
	return 1;
}

static void
ret_push_event(Uint8 *data, Uint16 len)
{
	SDL_Event event;
	SDL_zero(event);
	event.type = ret_event;
	event.user.data1 = data;
	event.user.code = len;
	while(SDL_PushEvent(&event) < 0)
		SDL_Delay(25);
}

static int
ret_thread(void *p)
{
	Uint8 hdr[2];
	USED(p);
	for(;;) {
		int fd = ret_connect();
		if(fd < 0) {
			SDL_Delay(2000);
			continue;
		}
		SDL_LockMutex(ret_lock);
		ret_fd = fd;
		SDL_UnlockMutex(ret_lock);
		while(ret_read_full(fd, hdr, 2)) {
			Uint16 len = hdr[0] << 8 | hdr[1];
			Uint8 *data;
			if(len == 0 || len > RET_MAX_FRAME) {
				fprintf(stderr, "reticulum: bad frame length %d, reconnecting\n", len);
				break;
			}
			data = malloc(len);
			if(!data || !ret_read_full(fd, data, len)) {
				free(data);
				break;
			}
			ret_push_event(data, len);
		}
		SDL_LockMutex(ret_lock);
		ret_fd = -1;
		close(fd);
		SDL_UnlockMutex(ret_lock);
		ret_bridge_flags = 0;
		SDL_Delay(1000);
	}
	return 0;
}

static int
ret_send(const Uint8 *data, Uint16 len)
{
	Uint8 hdr[2] = {len >> 8, len & 0xff};
	int ok = 0;
	SDL_LockMutex(ret_lock);
	if(ret_fd >= 0) {
		ok = send(ret_fd, hdr, 2, MSG_NOSIGNAL) == 2 &&
			send(ret_fd, data, len, MSG_NOSIGNAL) == (ssize_t)len;
		if(!ok) shutdown(ret_fd, SHUT_RDWR); /* let the reader thread reconnect */
	}
	SDL_UnlockMutex(ret_lock);
	return ok;
}

static void
ret_init(void)
{
	ret_lock = SDL_CreateMutex();
	ret_event = SDL_RegisterEvents(1);
	SDL_DetachThread(SDL_CreateThread(ret_thread, "reticulum", NULL));
}

#else /* !RET_ENABLED */

static int ret_send(const Uint8 *data, Uint16 len) { USED(data), USED(len); return 0; }
static void ret_init(void) { ret_event = SDL_RegisterEvents(1); }

#endif

/* main thread: a frame arrived from the bridge */
static void
ret_on_event(SDL_Event *event)
{
	Uint8 *data = event->user.data1;
	Uint16 len = event->user.code;
	if(!data) return;
	if(data[0] == RET_TYPE_STATE && len >= 2)
		ret_bridge_flags = data[1];
	if(ret_qlen == RET_QUEUE) {
		free(data);
		ret_dropped = 1;
	} else {
		RetFrame *f = &ret_queue[(ret_qhead + ret_qlen) % RET_QUEUE];
		f->data = data, f->len = len;
		ret_qlen++;
	}
	if(ret_vector)
		uxn_eval(ret_vector);
}

static void
ret_flush(void)
{
	while(ret_qlen) {
		free(ret_queue[ret_qhead].data);
		ret_qhead = (ret_qhead + 1) % RET_QUEUE, ret_qlen--;
	}
	ret_dropped = 0;
}

/* clang-format off */

static Uint8 ret_dei_status(void) { return ret_connected() | (ret_bridge_flags & 0x3) << 1 | ret_dropped << 3; }
static Uint8 ret_dei_queue(void) { return ret_qlen; }
static void ret_deo_vector(void) { ret_vector = peek2(&dev[0xd0]); }

/* clang-format on */

static void
ret_deo_read(void)
{
	Uint16 addr = peek2(&dev[0xd8]), cap = peek2(&dev[0xd6]), n = 0;
	ret_dropped = 0;
	if(ret_qlen) {
		RetFrame *f = &ret_queue[ret_qhead];
		n = f->len < cap ? f->len : cap;
		if((unsigned int)addr + n > 0x10000) n = 0x10000 - addr;
		memcpy(&ram[addr], f->data, n);
		free(f->data);
		ret_qhead = (ret_qhead + 1) % RET_QUEUE, ret_qlen--;
	}
	poke2(&dev[0xd4], n);
}

static void
ret_deo_write(void)
{
	Uint16 addr = peek2(&dev[0xd8]), len = peek2(&dev[0xd6]), n = 0;
	if(len && len <= RET_MAX_FRAME && (unsigned int)addr + len <= 0x10000 && ret_send(&ram[addr], len))
		n = len;
	poke2(&dev[0xd4], n);
}
